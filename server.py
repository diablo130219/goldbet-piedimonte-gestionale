#!/usr/bin/env python3
"""GoldBet Piedimonte - gestionale interno multi-postazione senza dipendenze esterne."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'static'
BRAND_DIR = Path(os.environ.get('GB_BRAND_DIR', str(STATIC)))
DB_PATH = Path(os.environ.get('GB_DB_PATH', str(ROOT / 'data' / 'gestionale.sqlite3')))
ZONE = ZoneInfo('Europe/Rome')
SESSION_HOURS = 12
_LOCK = threading.RLock()
_ATTEMPTS = {}


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def current_date():
    return datetime.now(ZONE).date().isoformat()


def money(value):
    """Accept euro strings/integers in decimal notation; return cents, no binary rounding."""
    if isinstance(value, bool) or value is None:
        raise ValueError('Importo non valido.')
    s = str(value).strip().replace(' ', '').replace('€', '')
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        v = Decimal(s)
    except (InvalidOperation, ValueError):
        raise ValueError('Inserisci un importo valido.')
    if not v.is_finite() or v < 0 or v > 100000000 or v.as_tuple().exponent < -2:
        raise ValueError('Importo fuori limite o con più di due decimali.')
    return int(v * 100)


def euros(cents):
    return f'{cents / 100:.2f}'


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 15000')
    return conn


@contextmanager
def db_session():
    connection = db()
    try:
        with connection:
            yield connection
    finally:
        connection.close()

def init_db():
    with db_session() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
          CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            full_name TEXT NOT NULL, password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','operator')),
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            expires_at TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
            created_at TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY, cash_number INTEGER NOT NULL CHECK(cash_number IN (1,2)),
            user_id INTEGER NOT NULL REFERENCES users(id),
            opening_date TEXT NOT NULL, opened_at TEXT NOT NULL,
            initial_cents INTEGER NOT NULL,
            green_cents INTEGER NOT NULL DEFAULT 0,
            red_cents INTEGER NOT NULL DEFAULT 0,
            physical_cents INTEGER, expected_cents INTEGER,
            difference_cents INTEGER,
            close_note TEXT NOT NULL DEFAULT '', closed_at TEXT
          );
          CREATE UNIQUE INDEX IF NOT EXISTS ux_active_shift_per_cash
            ON shifts(cash_number) WHERE closed_at IS NULL;
          CREATE TABLE IF NOT EXISTS movements (
            id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id),
            shift_id INTEGER NOT NULL REFERENCES shifts(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL CHECK(kind IN ('debit','credit')),
            amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
            note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            voided_at TEXT, voided_by INTEGER REFERENCES users(id), void_reason TEXT
          );
          CREATE INDEX IF NOT EXISTS ix_movements_client ON movements(client_id,id);
          CREATE INDEX IF NOT EXISTS ix_movements_shift ON movements(shift_id,id);
          CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id),
            kind TEXT NOT NULL CHECK(kind IN ('overdue','paid')),
            message TEXT NOT NULL, amount_cents INTEGER NOT NULL,
            created_at TEXT NOT NULL, resolved_at TEXT
          );
          CREATE INDEX IF NOT EXISTS ix_notifications_client ON notifications(client_id,kind,resolved_at);
          CREATE TABLE IF NOT EXISTS notification_reads (
            notification_id INTEGER NOT NULL REFERENCES notifications(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            read_at TEXT NOT NULL,
            PRIMARY KEY(notification_id,user_id)
          );
          CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL, entity TEXT NOT NULL, entity_id INTEGER,
            details TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
          );
        ''')


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    result = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 260_000)
    return salt.hex() + ':' + result.hex()


def verify_password(password, stored):
    try:
        salt, expected = stored.split(':', 1)
        found = hash_password(password, bytes.fromhex(salt)).split(':', 1)[1]
        return hmac.compare_digest(expected, found)
    except Exception:
        return False


def validate_password(v):
    if not isinstance(v, str) or len(v) < 10 or len(v) > 128:
        raise ValueError('La password deve avere da 10 a 128 caratteri.')
    return v


def audit(c, actor, action, entity, entity_id, details=None):
    c.execute('INSERT INTO audit(actor_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)',
              (actor, action, entity, entity_id, json.dumps(details or {}, ensure_ascii=False), now_utc()))


def as_dict(row):
    return dict(row) if row is not None else None


def client_debt(c, client_id):
    rows = c.execute('SELECT kind,amount_cents,created_at FROM movements '
                     'WHERE client_id=? AND voided_at IS NULL ORDER BY id', (client_id,)).fetchall()
    credits = sum(r['amount_cents'] for r in rows if r['kind'] == 'credit')
    debit_sum = sum(r['amount_cents'] for r in rows if r['kind'] == 'debit')
    total = debit_sum - credits
    first_unpaid = None
    for r in rows:
        if r['kind'] == 'debit':
            if credits >= r['amount_cents']:
                credits -= r['amount_cents']
            else:
                first_unpaid = r['created_at']
                break
    return max(0, total), first_unpaid


def serialize_client(c, row):
    result = as_dict(row)
    outstanding, first = client_debt(c, row['id'])
    days = None
    overdue = False
    if first:
        diff = datetime.now(timezone.utc) - datetime.fromisoformat(first)
        days = max(0, int(diff.total_seconds() // 86400))
        overdue = diff >= timedelta(days=7)
    result.update(debt_cents=outstanding, first_unpaid_at=first,
                  days_open=days, overdue=overdue)
    return result


def reconcile_client(c, client_id, previous_debt=None, payment_amount=0):
    remaining, first = client_debt(c, client_id)
    utc = now_utc()
    overdue = bool(first and datetime.fromisoformat(utc) - datetime.fromisoformat(first) >= timedelta(days=7))
    if not overdue:
        c.execute("UPDATE notifications SET resolved_at=? WHERE client_id=? AND kind='overdue' AND resolved_at IS NULL",
                  (utc, client_id))
    else:
        active = c.execute("SELECT id FROM notifications WHERE client_id=? AND kind='overdue' AND resolved_at IS NULL",
                           (client_id,)).fetchone()
        if not active:
            c.execute("INSERT INTO notifications(client_id,kind,message,amount_cents,created_at) VALUES(?,'overdue',?,?,?)",
                      (client_id, 'Non saldato dopo 7 giorni', remaining, utc))
        else:
            c.execute('UPDATE notifications SET amount_cents=? WHERE id=?', (remaining, active['id']))
    if previous_debt is not None and previous_debt > 0 and remaining == 0 and payment_amount > 0:
        c.execute("INSERT INTO notifications(client_id,kind,message,amount_cents,created_at) VALUES(?,'paid',?,?,?)",
                  (client_id, 'Debito completamente saldato', payment_amount, utc))
    return remaining


def refresh_overdues(c):
    ids = c.execute('SELECT id FROM clients').fetchall()
    for row in ids:
        reconcile_client(c, row['id'])


def shift_totals(c, shift):
    r = c.execute('SELECT '
                  "COALESCE(SUM(CASE WHEN kind='credit' THEN amount_cents ELSE 0 END),0) AS credits,"
                  "COALESCE(SUM(CASE WHEN kind='debit' THEN amount_cents ELSE 0 END),0) AS debits "
                  'FROM movements WHERE shift_id=? AND voided_at IS NULL', (shift['id'],)).fetchone()
    result = as_dict(shift)
    result['blue_cents'] = result['green_cents'] - result['red_cents']
    result['entries_cents'] = r['credits']
    result['exits_cents'] = r['debits']
    result['calculated_cents'] = (result['blue_cents'] + result['initial_cents'] + r['credits'] - r['debits'])
    return result


def shift_movements(c, shift_id):
    return [dict(r) for r in c.execute('''SELECT m.*,cl.first_name,cl.last_name,u.full_name AS operator_name
      FROM movements m JOIN clients cl ON cl.id=m.client_id JOIN users u ON u.id=m.user_id
      WHERE m.shift_id=? ORDER BY m.id DESC''', (shift_id,))]


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


class Handler(BaseHTTPRequestHandler):
    server_version = 'GB-Piedimonte/1.0'

    def log_message(self, fmt, *args):
        print('%s %s' % (self.log_date_time_string(), fmt % args), file=sys.stderr)

    def respond(self, status, value, cookie=None):
        raw = json.dumps(value, ensure_ascii=False).encode('utf8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'")
        self.send_header('Referrer-Policy', 'no-referrer')
        if os.environ.get('GB_PUBLIC') == '1':
            self.send_header('Strict-Transport-Security','max-age=31536000; includeSubDomains')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        if 'application/json' not in self.headers.get('Content-Type', ''):
            raise ApiError(415, 'Invia dati JSON.')
        if int(self.headers.get('Content-Length', '0')) > 250000:
            raise ApiError(413, 'Dati troppo grandi.')
        try:
            length = int(self.headers.get('Content-Length', '0'))
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict): raise ValueError('body non oggetto')
            return data
        except Exception:
            raise ApiError(400, 'Dati JSON non validi.')

    def safe_post_origin(self):
        # SameSite cookies + same-origin checks. JSON is required for state changes.
        origin = self.headers.get('Origin', '')
        host = self.headers.get('Host', '')
        if origin and urlparse(origin).netloc != host:
            raise ApiError(403, 'Richiesta da origine non autorizzata.')

    def auth(self, c):
        header = self.headers.get('Cookie', '')
        cookie = SimpleCookie()
        try: cookie.load(header)
        except Exception: pass
        token = cookie.get('gb_session')
        if token is None:
            raise ApiError(401, 'Effettua l’accesso.')
        hashed = hashlib.sha256(token.value.encode()).hexdigest()
        user = c.execute('''SELECT u.id,u.username,u.full_name,u.role,u.active,s.expires_at
                          FROM sessions s JOIN users u ON s.user_id=u.id
                          WHERE s.token_hash=?''', (hashed,)).fetchone()
        if not user or not user['active'] or user['expires_at'] < now_utc():
            raise ApiError(401, 'Sessione scaduta. Accedi nuovamente.')
        return dict(user)

    def admin(self, user):
        if user['role'] != 'admin':
            raise ApiError(403, 'Funzione riservata all’amministratore.')

    def current_shift(self, c, cash):
        if cash not in (1, 2): raise ApiError(400, 'Cassa non valida.')
        return c.execute('SELECT * FROM shifts WHERE cash_number=? AND closed_at IS NULL', (cash,)).fetchone()

    def authorized_shift(self, c, user, shift_id, open_required=True):
        shift = c.execute('SELECT * FROM shifts WHERE id=?', (shift_id,)).fetchone()
        if not shift: raise ApiError(404, 'Distinta non trovata.')
        if open_required and shift['closed_at']: raise ApiError(409, 'La distinta è già chiusa.')
        if open_required and shift['user_id'] != user['id'] and user['role'] != 'admin':
            raise ApiError(403, 'Questa distinta è aperta da un altro operatore.')
        return shift

    def do_GET(self):
        self.dispatch('GET')

    def do_POST(self):
        self.dispatch('POST')

    def dispatch(self, method):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if method == 'GET' and path == '/healthz':
                return self.respond(200, {'ok': True})
            if method == 'GET' and not path.startswith('/api/'):
                return self.serve_static(path)
            if method == 'POST': self.safe_post_origin()
            args = parse_qs(parsed.query)
            with _LOCK:
                with db_session() as c:
                    if path == '/api/bootstrap' and method == 'GET':
                        n = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
                        return self.respond(200, {'needs_setup': n == 0, 'online_setup': bool(os.environ.get('GB_SETUP_TOKEN'))})
                    if path == '/api/setup' and method == 'POST':
                        b = self.body()
                        setup_secret = os.environ.get('GB_SETUP_TOKEN', '')
                        if setup_secret:
                            if len(setup_secret) < 24:
                                raise ApiError(503, 'Il codice di prima configurazione del server è troppo breve.')
                            submitted = str(b.get('setup_token') or '')
                            if not hmac.compare_digest(submitted, setup_secret):
                                raise ApiError(403, 'Codice di attivazione errato.')
                        elif not ipaddress.ip_address(self.client_address[0]).is_loopback:
                            raise ApiError(403, 'Prima configurazione consentita solo dal PC server.')
                        c.execute('BEGIN IMMEDIATE')
                        if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
                            raise ApiError(409, 'Configurazione già completata.')
                        password = validate_password(b.get('password'))
                        name = str(b.get('full_name', '')).strip()
                        if len(name) < 2 or len(name) > 80: raise ApiError(400, 'Inserisci il nome operatore.')
                        c.execute('INSERT INTO users(username,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                                  ('admin', name, hash_password(password), 'admin', now_utc()))
                        c.commit()
                        return self.respond(201, {'ok': True})
                    if path == '/api/login' and method == 'POST':
                        b = self.body()
                        username = str(b.get('username', '')).strip()
                        pw = str(b.get('password', ''))
                        k = (self.client_address[0], username.lower())
                        attempts = [x for x in _ATTEMPTS.get(k, []) if time.time() - x < 900]
                        if len(attempts) >= 8: raise ApiError(429, 'Troppi tentativi. Riprova tra 15 minuti.')
                        u = c.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE AND active=1', (username,)).fetchone()
                        if not u or not verify_password(pw, u['password_hash']):
                            attempts.append(time.time()); _ATTEMPTS[k] = attempts
                            raise ApiError(401, 'Credenziali errate.')
                        _ATTEMPTS.pop(k, None)
                        token = secrets.token_urlsafe(36)
                        c.execute('INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)',
                                  (hashlib.sha256(token.encode()).hexdigest(), u['id'],
                                   (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat(timespec='seconds')))
                        c.commit()
                        cookie = f'gb_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_HOURS * 3600}'
                        if os.environ.get('GB_SECURE_COOKIE') == '1' or os.environ.get('GB_PUBLIC') == '1': cookie += '; Secure'
                        return self.respond(200, {'user': dict(id=u['id'], username=u['username'],
                                                              full_name=u['full_name'], role=u['role'])}, cookie=cookie)
                    user = self.auth(c)
                    if path == '/api/me' and method == 'GET':
                        return self.respond(200, {'user': {k: user[k] for k in ('id','username','full_name','role')}})
                    if path == '/api/logout' and method == 'POST':
                        cookie = SimpleCookie(); cookie.load(self.headers.get('Cookie',''))
                        if cookie.get('gb_session'):
                            hashed = hashlib.sha256(cookie['gb_session'].value.encode()).hexdigest()
                            c.execute('DELETE FROM sessions WHERE token_hash=?', (hashed,))
                        c.commit()
                        return self.respond(200, {'ok': True}, 'gb_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0')
                    if path == '/api/overview' and method == 'GET':
                        cash = int(args.get('cash',['0'])[0])
                        shift = self.current_shift(c, cash)
                        if not shift:
                            return self.respond(200, {'shift': None, 'movements': []})
                        return self.respond(200, {'shift': shift_totals(c,shift), 'movements':shift_movements(c,shift['id'])})
                    if path == '/api/shifts/open' and method == 'POST':
                        b = self.body()
                        cash = int(b.get('cash',0))
                        if cash not in (1,2): raise ApiError(400, 'Cassa non valida.')
                        initial = money(b.get('initial',''))
                        c.execute('BEGIN IMMEDIATE')
                        if self.current_shift(c,cash): raise ApiError(409, 'Esiste già una distinta aperta su questa cassa.')
                        cur = c.execute('INSERT INTO shifts(cash_number,user_id,opening_date,opened_at,initial_cents) VALUES(?,?,?,?,?)',
                                        (cash,user['id'],current_date(),now_utc(),initial))
                        audit(c,user['id'],'open','shift',cur.lastrowid,{'initial_cents':initial})
                        c.commit()
                        return self.respond(201, {'id':cur.lastrowid})
                    if path == '/api/shifts/totals' and method == 'POST':
                        b = self.body()
                        sid = int(b.get('shift_id',0))
                        green = money(b.get('green',''))
                        red = money(b.get('red',''))
                        c.execute('BEGIN IMMEDIATE')
                        shift = self.authorized_shift(c,user,sid)
                        c.execute('UPDATE shifts SET green_cents=?,red_cents=? WHERE id=?', (green,red,sid))
                        audit(c,user['id'],'update_totals','shift',sid,{'old_green':shift['green_cents'],'old_red':shift['red_cents'], 'green':green,'red':red})
                        c.commit()
                        return self.respond(200, {'ok':True})
                    if path == '/api/clients' and method == 'GET':
                        items = [serialize_client(c,r) for r in c.execute('SELECT * FROM clients ORDER BY last_name COLLATE NOCASE,first_name COLLATE NOCASE')]
                        return self.respond(200, {'clients': items})
                    if path == '/api/clients' and method == 'POST':
                        b = self.body()
                        first = ' '.join(str(b.get('first_name','')).strip().split())
                        last = ' '.join(str(b.get('last_name','')).strip().split())
                        if not (2<=len(first)<=70 and 2<=len(last)<=70):
                            raise ApiError(400, 'Nome e cognome obbligatori (minimo 2 caratteri).')
                        c.execute('BEGIN IMMEDIATE')
                        dup = c.execute('SELECT id FROM clients WHERE first_name=? COLLATE NOCASE AND last_name=? COLLATE NOCASE',(first,last)).fetchone()
                        if dup and not b.get('allow_homonym'):
                            raise ApiError(409, 'Cliente con lo stesso nome già presente. Controlla la rubrica; se omonimo, conferma l’inserimento.')
                        cur = c.execute('INSERT INTO clients(first_name,last_name,created_at) VALUES(?,?,?)',(first,last,now_utc()))
                        audit(c,user['id'],'create','client',cur.lastrowid)
                        c.commit()
                        return self.respond(201, {'id': cur.lastrowid})
                    match = re.fullmatch(r'/api/clients/(\d+)', path)
                    if match and method == 'GET':
                        client_id = int(match.group(1))
                        row = c.execute('SELECT * FROM clients WHERE id=?',(client_id,)).fetchone()
                        if not row: raise ApiError(404, 'Cliente non trovato.')
                        moves = [dict(r) for r in c.execute('''SELECT m.*, s.cash_number, u.full_name AS operator_name
                          FROM movements m JOIN shifts s ON s.id=m.shift_id JOIN users u ON u.id=m.user_id
                          WHERE m.client_id=? ORDER BY m.id DESC''',(client_id,))]
                        return self.respond(200, {'client':serialize_client(c,row), 'movements':moves})
                    match = re.fullmatch(r'/api/clients/(\d+)/edit', path)
                    if match and method == 'POST':
                        cid = int(match.group(1))
                        b = self.body()
                        first = ' '.join(str(b.get('first_name','')).strip().split())
                        last = ' '.join(str(b.get('last_name','')).strip().split())
                        if not (2<=len(first)<=70 and 2<=len(last)<=70):
                            raise ApiError(400,'Nome e cognome obbligatori (minimo 2 caratteri).')
                        c.execute('BEGIN IMMEDIATE')
                        previous = c.execute('SELECT * FROM clients WHERE id=?',(cid,)).fetchone()
                        if not previous: raise ApiError(404,'Cliente non trovato.')
                        c.execute('UPDATE clients SET first_name=?,last_name=? WHERE id=?',(first,last,cid))
                        audit(c,user['id'],'update','client',cid,{'old_name':previous['first_name']+' '+previous['last_name'],'new_name':first+' '+last})
                        c.commit()
                        return self.respond(200,{'ok':True})
                    if path == '/api/movements' and method == 'POST':
                        b = self.body()
                        try: sid, cid = int(b.get('shift_id',0)), int(b.get('client_id',0))
                        except Exception: raise ApiError(400,'Distinta o cliente non valido.')
                        kind = b.get('kind')
                        if kind not in ('debit','credit'): raise ApiError(400,'Tipo movimento non valido.')
                        amount = money(b.get('amount',''))
                        if amount<=0: raise ApiError(400,'L’importo deve essere maggiore di zero.')
                        note = str(b.get('note','')).strip()[:300]
                        c.execute('BEGIN IMMEDIATE')
                        shift = self.authorized_shift(c,user,sid)
                        if not c.execute('SELECT 1 FROM clients WHERE id=?',(cid,)).fetchone():
                            raise ApiError(404,'Cliente non trovato.')
                        previous, _ = client_debt(c,cid)
                        if kind=='credit' and amount>previous:
                            raise ApiError(400,f'Pagamento superiore al debito residuo ({euros(previous)} €).')
                        cur = c.execute('INSERT INTO movements(client_id,shift_id,user_id,kind,amount_cents,note,created_at) VALUES(?,?,?,?,?,?,?)',
                                  (cid,sid,user['id'],kind,amount,note,now_utc()))
                        reconcile_client(c,cid,previous,amount if kind=='credit' else 0)
                        audit(c,user['id'],'create','movement',cur.lastrowid,{'client':cid,'kind':kind,'amount_cents':amount,'cash':shift['cash_number']})
                        c.commit()
                        return self.respond(201, {'id':cur.lastrowid})
                    match = re.fullmatch(r'/api/movements/(\d+)/void',path)
                    if match and method == 'POST':
                        mid = int(match.group(1)); b=self.body()
                        reason = str(b.get('reason','')).strip()
                        if len(reason)<3: raise ApiError(400,'Indica il motivo dell’annullamento (almeno 3 caratteri).')
                        c.execute('BEGIN IMMEDIATE')
                        movement = c.execute('SELECT * FROM movements WHERE id=?',(mid,)).fetchone()
                        if not movement: raise ApiError(404,'Movimento non trovato.')
                        if movement['voided_at']: raise ApiError(409,'Movimento già annullato.')
                        self.authorized_shift(c,user,movement['shift_id'])
                        cid=movement['client_id']
                        prior,_ = client_debt(c,cid)
                        # A historical debit cannot be voided when it would invalidate later repayments.
                        rows=c.execute('SELECT * FROM movements WHERE client_id=? AND voided_at IS NULL AND id<>? ORDER BY id',(cid,mid)).fetchall()
                        running=0
                        for row in rows:
                            running += row['amount_cents'] if row['kind']=='debit' else -row['amount_cents']
                            if running<0: raise ApiError(409,'Annullamento impossibile: renderebbe superiore al debito un pagamento successivo.')
                        c.execute('UPDATE movements SET voided_at=?,voided_by=?,void_reason=? WHERE id=?',
                                  (now_utc(),user['id'],reason,mid))
                        reconcile_client(c,cid)
                        audit(c,user['id'],'void','movement',mid,{'reason':reason,'previous_debt':prior})
                        c.commit()
                        return self.respond(200,{'ok':True})
                    if path == '/api/shifts/close' and method == 'POST':
                        b = self.body()
                        sid = int(b.get('shift_id',0)); physical=money(b.get('physical',''))
                        note = str(b.get('note','')).strip()[:600]
                        c.execute('BEGIN IMMEDIATE')
                        shift = self.authorized_shift(c,user,sid)
                        totals = shift_totals(c,shift)
                        expected = totals['calculated_cents']
                        delta = expected - physical
                        c.execute('UPDATE shifts SET physical_cents=?,expected_cents=?,difference_cents=?,close_note=?,closed_at=? WHERE id=?',
                                  (physical,expected,delta,note,now_utc(),sid))
                        audit(c,user['id'],'close','shift',sid,{'expected':expected,'physical':physical,'difference':delta})
                        c.commit()
                        return self.respond(200,{'difference_cents':delta,'expected_cents':expected})
                    if path == '/api/shifts/archive' and method == 'GET':
                        cash=int(args.get('cash',['0'])[0]);
                        if cash not in (1,2): raise ApiError(400,'Cassa non valida.')
                        rows=c.execute('''SELECT s.*,u.full_name AS operator_name FROM shifts s JOIN users u ON u.id=s.user_id
                          WHERE s.cash_number=? AND s.closed_at IS NOT NULL ORDER BY s.id DESC LIMIT 250''',(cash,)).fetchall()
                        return self.respond(200, {'shifts':[shift_totals(c,row) for row in rows]})
                    match = re.fullmatch(r'/api/shifts/(\d+)',path)
                    if match and method=='GET':
                        sid=int(match.group(1))
                        shift=c.execute('''SELECT s.*,u.full_name AS operator_name FROM shifts s JOIN users u ON u.id=s.user_id WHERE s.id=?''',(sid,)).fetchone()
                        if not shift: raise ApiError(404,'Distinta non trovata.')
                        return self.respond(200,{'shift':shift_totals(c,shift),'movements':shift_movements(c,sid)})
                    if path == '/api/notifications' and method == 'GET':
                        c.execute('BEGIN IMMEDIATE')
                        refresh_overdues(c)
                        c.commit()
                        result=[dict(r) for r in c.execute('''SELECT n.*,cl.first_name,cl.last_name,
                           (CASE WHEN nr.user_id IS NULL THEN 0 ELSE 1 END) AS is_read
                           FROM notifications n JOIN clients cl ON cl.id=n.client_id
                           LEFT JOIN notification_reads nr ON nr.notification_id=n.id AND nr.user_id=?
                           WHERE (n.kind='overdue' AND n.resolved_at IS NULL)
                              OR (n.kind='paid' AND n.created_at>=?)
                           ORDER BY n.id DESC LIMIT 150''', (user['id'],(datetime.now(timezone.utc)-timedelta(days=90)).isoformat(timespec='seconds')))]
                        return self.respond(200,{'notifications':result,'unread':sum(not n['is_read'] for n in result)})
                    if path == '/api/notifications/read' and method == 'POST':
                        b=self.body(); nid=int(b.get('id',0))
                        if not c.execute('SELECT id FROM notifications WHERE id=?',(nid,)).fetchone():
                            raise ApiError(404,'Notifica inesistente.')
                        c.execute('INSERT OR IGNORE INTO notification_reads(notification_id,user_id,read_at) VALUES(?,?,?)',
                                  (nid,user['id'],now_utc()))
                        c.commit()
                        return self.respond(200,{'ok':True})
                    if path == '/api/users' and method == 'GET':
                        self.admin(user)
                        rows = [dict(r) for r in c.execute('SELECT id,username,full_name,role,active,created_at FROM users ORDER BY id')]
                        return self.respond(200,{'users':rows})
                    if path == '/api/users' and method == 'POST':
                        self.admin(user); b=self.body()
                        username=str(b.get('username','')).strip().lower()
                        name=' '.join(str(b.get('full_name','')).strip().split())
                        password=validate_password(b.get('password'))
                        if not re.fullmatch(r'[a-z0-9._-]{3,35}',username): raise ApiError(400,'Username: 3-35 caratteri, lettere, numeri, punti o trattini.')
                        if not (2<=len(name)<=80): raise ApiError(400,'Nome operatore obbligatorio.')
                        try:
                            cur=c.execute('INSERT INTO users(username,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                                           (username,name,hash_password(password),'operator',now_utc()))
                        except sqlite3.IntegrityError: raise ApiError(409,'Questo username esiste già.')
                        audit(c,user['id'],'create','user',cur.lastrowid)
                        c.commit()
                        return self.respond(201,{'id':cur.lastrowid})
                    if path == '/api/users/password' and method == 'POST':
                        b=self.body(); pw=validate_password(b.get('new_password'))
                        old=c.execute('SELECT password_hash FROM users WHERE id=?',(user['id'],)).fetchone()
                        if not verify_password(str(b.get('current_password','')),old['password_hash']):
                            raise ApiError(403,'Password attuale errata.')
                        c.execute('UPDATE users SET password_hash=? WHERE id=?',(hash_password(pw),user['id']))
                        c.execute('DELETE FROM sessions WHERE user_id=? AND token_hash<>?',
                                  (user['id'],hashlib.sha256(SimpleCookie(self.headers.get('Cookie',''))['gb_session'].value.encode()).hexdigest()))
                        audit(c,user['id'],'change_password','user',user['id'])
                        c.commit()
                        return self.respond(200,{'ok':True})
                    if path == '/api/users/reset-password' and method == 'POST':
                        self.admin(user); b=self.body(); target=int(b.get('id',0)); pw=validate_password(b.get('password'))
                        row=c.execute('SELECT id FROM users WHERE id=?',(target,)).fetchone()
                        if not row: raise ApiError(404,'Operatore non trovato.')
                        c.execute('UPDATE users SET password_hash=? WHERE id=?',(hash_password(pw),target))
                        c.execute('DELETE FROM sessions WHERE user_id=?',(target,))
                        audit(c,user['id'],'reset_password','user',target)
                        c.commit(); return self.respond(200,{'ok':True})
                    if path == '/api/backup' and method == 'GET':
                        self.admin(user)
                        fd, fn = tempfile.mkstemp(suffix='.sqlite3')
                        os.close(fd)
                        try:
                            with sqlite3.connect(fn) as target: c.backup(target)
                            raw = Path(fn).read_bytes()
                        finally:
                            Path(fn).unlink(missing_ok=True)
                        self.send_response(200)
                        self.send_header('Content-Type','application/octet-stream')
                        self.send_header('Content-Disposition',f'attachment; filename="GoldBet-Piedimonte-backup-{current_date()}.sqlite3"')
                        self.send_header('Content-Length',str(len(raw)))
                        self.send_header('Cache-Control','no-store')
                        self.end_headers(); self.wfile.write(raw)
                        return
                    if path == '/api/settings/logo' and method == 'POST':
                        self.admin(user); b=self.body()
                        encoded=str(b.get('data',''))
                        match=re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)',encoded)
                        if not match: raise ApiError(400,'Carica un logo PNG, JPG oppure WebP.')
                        blob=base64.b64decode(match.group(2),validate=True)
                        if len(blob)>1_500_000: raise ApiError(400,'Logo troppo grande (massimo 1,5 MB).')
                        ext={'png':'png','jpeg':'jpg','webp':'webp'}[match.group(1)]
                        if (ext=='png' and not blob.startswith(b'\x89PNG\r\n\x1a\n')) or (ext=='jpg' and not blob.startswith(b'\xff\xd8')) or (ext=='webp' and blob[8:12]!=b'WEBP'):
                            raise ApiError(400,'File immagine non riconosciuto.')
                        STATIC.mkdir(exist_ok=True)
                        BRAND_DIR.mkdir(parents=True, exist_ok=True)
                        for old in BRAND_DIR.glob('brand_upload.*'): old.unlink()
                        (BRAND_DIR/f'brand_upload.{ext}').write_bytes(blob)
                        audit(c,user['id'],'change_logo','settings',None)
                        c.commit(); return self.respond(200,{'ok':True})
                    if path == '/api/settings' and method == 'GET':
                        files=list(BRAND_DIR.glob('brand_upload.*'))
                        return self.respond(200,{'logo_path':('/static/'+files[0].name) if files else None})
                    raise ApiError(404, 'Pagina o operazione non trovata.')
        except ApiError as e:
            self.respond(e.status,{'error':e.message})
        except (ValueError,TypeError) as e:
            self.respond(400,{'error':str(e) or 'Dati non validi.'})
        except sqlite3.IntegrityError:
            self.respond(409,{'error':'Conflitto tra dati: aggiorna la pagina e riprova.'})
        except Exception as e:
            print('ERROR:',repr(e),file=sys.stderr)
            try:self.respond(500,{'error':'Errore del server. Contatta l’amministratore.'})
            except (BrokenPipeError,ConnectionResetError):pass

    def serve_static(self,path):
        if path == '/': path='/index.html'
        if path.startswith('/static/'): path=path[len('/static/'):]
        else: path=path.lstrip('/')
        # Only uploaded logo files live on the persistent disk in cloud mode.
        root = BRAND_DIR if re.fullmatch(r'brand_upload\.(png|jpg|jpeg|webp)',path) else STATIC
        requested=(root/path).resolve()
        if not requested.is_relative_to(root.resolve()) or not requested.is_file():
            self.send_error(404);return
        mime,_=mimetypes.guess_type(str(requested))
        if requested.suffix=='.js':mime='application/javascript'
        data=requested.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',(mime or 'application/octet-stream')+'; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'")
        self.send_header('Cache-Control','no-cache')
        if os.environ.get('GB_PUBLIC') == '1':
            self.send_header('Strict-Transport-Security','max-age=31536000; includeSubDomains')
        self.end_headers(); self.wfile.write(data)


def notification_monitor(stop_event):
    # Creates overdue alerts while the server runs, independently from browser activity.
    while not stop_event.is_set():
        try:
            with _LOCK:
                with db_session() as c:
                    c.execute('BEGIN IMMEDIATE')
                    refresh_overdues(c)
                    c.commit()
        except Exception as exc:
            print('Monitor notifiche:',repr(exc),file=sys.stderr)
        stop_event.wait(60)


def run(port=None):
    if os.environ.get('GB_PUBLIC') == '1' and not os.environ.get('GB_SETUP_TOKEN'):
        raise RuntimeError('GB_SETUP_TOKEN è obbligatorio per esporre il gestionale online.')
    init_db()
    port = int(port or os.environ.get('PORT') or os.environ.get('GB_PORT',8787))
    host = os.environ.get('GB_HOST','0.0.0.0')
    server = ThreadingHTTPServer((host,port),Handler)
    print(f'\n  GOLD BET PIEDIMONTE — SERVER AVVIATO\n'
          f'  Sul PC server: http://127.0.0.1:{port}\n'
          f'  Su Cassa 1 e Cassa 2: http://IP-DEL-PC-SERVER:{port}\n'
          f'  Database: {DB_PATH}\n'
          f'  Configurazione: codice privato GB_SETUP_TOKEN, se impostato.\n'
          f'  Online: usare esclusivamente HTTPS dietro un reverse proxy affidabile.\n', flush=True)
    stop_event = threading.Event()
    worker = threading.Thread(target=notification_monitor, args=(stop_event,), daemon=True)
    worker.start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        stop_event.set()
        server.server_close()


if __name__=='__main__': run()