"""E2E tests for two tills, shared clients, overdue FIFO and reconciliation."""
import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class TestWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(cls.temp.name) / 'test.sqlite3'
        server.init_db()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1',0), server.Handler)
        cls.url = f'http://127.0.0.1:{cls.http.server_address[1]}'
        cls.thread = threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join(timeout=3)
        cls.temp.cleanup()

    def api(self,opener,path,data=None):
        raw=json.dumps(data).encode() if data is not None else None
        req=urllib.request.Request(self.url+path,raw,headers={'Content-Type':'application/json'} if data is not None else {},method='POST' if data is not None else 'GET')
        try:
            with opener.open(req,timeout=5) as r:
                if r.headers.get_content_type()=='application/octet-stream':return r.read()
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {'status':e.code,'error':json.loads(e.read()).get('error')}

    def login(self,u,password):
        opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        assert self.api(opener,'/api/login',{'username':u,'password':password}).get('user')
        return opener

    def test_two_cash_shared_ledger_and_close(self):
        guest=urllib.request.build_opener()
        self.assertTrue(self.api(guest,'/api/bootstrap')['needs_setup'])
        self.assertTrue(self.api(guest,'/api/setup',{'full_name':'Responsabile','password':'SuperSegreta123!'}).get('ok'))
        admin=self.login('admin','SuperSegreta123!')
        self.assertIn('id',self.api(admin,'/api/users',{'username':'operatore1','full_name':'Operatore Uno','password':'PasswordFortissima1!'}))
        self.assertIn('id',self.api(admin,'/api/users',{'username':'operatore2','full_name':'Operatore Due','password':'PasswordFortissima2!'}))
        one=self.login('operatore1','PasswordFortissima1!')
        two=self.login('operatore2','PasswordFortissima2!')
        s1=self.api(one,'/api/shifts/open',{'cash':1,'initial':'500,00'})['id']
        s2=self.api(two,'/api/shifts/open',{'cash':2,'initial':'300,00'})['id']
        self.assertEqual(self.api(two,'/api/shifts/open',{'cash':1,'initial':'200,00'})['status'],409)
        self.assertTrue(self.api(one,'/api/shifts/totals',{'shift_id':s1,'green':'2890,85','red':'361,37'})['ok'])
        client=self.api(one,'/api/clients',{'first_name':'Mario','last_name':'Rossi'})['id']
        m1=self.api(one,'/api/movements',{'shift_id':s1,'client_id':client,'kind':'debit','amount':'100,00'})['id']
        self.assertEqual(self.api(two,'/api/movements',{'shift_id':s1,'client_id':client,'kind':'debit','amount':'10,00'})['status'],403)
        with server.db_session() as c:
            c.execute('UPDATE movements SET created_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(days=8)).isoformat(timespec='seconds'),m1))
        self.api(two,'/api/movements',{'shift_id':s2,'client_id':client,'kind':'debit','amount':'50,00'})
        self.assertEqual(self.api(two,'/api/clients')['clients'][0]['debt_cents'],15000)
        notices=self.api(one,'/api/notifications')['notifications']
        self.assertEqual(len([n for n in notices if n['kind']=='overdue']),1)
        self.assertEqual(self.api(two,'/api/movements',{'shift_id':s2,'client_id':client,'kind':'credit','amount':'151,00'})['status'],400)
        # The oldest debt is now fully covered; the younger debt hasn't reached 7 days.
        self.api(one,'/api/movements',{'shift_id':s1,'client_id':client,'kind':'credit','amount':'100,00'})
        self.assertEqual(len([n for n in self.api(one,'/api/notifications')['notifications'] if n['kind']=='overdue']),0)
        self.api(two,'/api/movements',{'shift_id':s2,'client_id':client,'kind':'credit','amount':'50,00'})
        self.assertEqual(self.api(one,'/api/clients')['clients'][0]['debt_cents'],0)
        notices=self.api(two,'/api/notifications')['notifications']
        self.assertEqual(len([n for n in notices if n['kind']=='paid']),1)
        # The per-cash ledger is independent. Cassa 1: blue + opening + credits - debits.
        s=self.api(one,'/api/overview?cash=1')['shift']
        self.assertEqual(s['blue_cents'],252948)
        self.assertEqual(s['calculated_cents'],302948)
        self.assertEqual(s['entries_cents'],10000)
        self.assertEqual(s['exits_cents'],10000)
        self.assertEqual(self.api(one,'/api/shifts/close',{'shift_id':s1,'physical':'3029,48','note':'Quadra'})['difference_cents'],0)
        self.assertEqual(self.api(one,'/api/movements',{'shift_id':s1,'client_id':client,'kind':'debit','amount':'1,00'})['status'],409)
        archived=self.api(one,'/api/shifts/archive?cash=1')['shifts']
        self.assertEqual(len(archived),1)
        self.assertEqual(self.api(two,'/api/shifts/archive?cash=2')['shifts'],[])
        # Optional customer fields: LIDL appears under L even without surname.
        self.assertEqual(self.api(admin,'/api/clients',{'first_name':'','last_name':''})['status'],400)
        lidl=self.api(admin,'/api/clients',{'first_name':'LIDL','last_name':''})['id']
        brico=self.api(admin,'/api/clients',{'first_name':'','last_name':'BRICO'})['id']
        registered=self.api(admin,'/api/clients')['clients']
        self.assertEqual([x['first_name']+' '+x['last_name'] for x in registered],
                         [' BRICO','LIDL ','Mario Rossi'])
        self.assertEqual(self.api(admin,f'/api/clients/{lidl}')['client']['last_name'],'')
        self.assertEqual(self.api(admin,f'/api/clients/{brico}')['client']['first_name'],'')
        self.assertEqual(self.api(admin,f'/api/clients/{lidl}/edit',{'first_name':'','last_name':'LIDL'})['ok'],True)
        self.assertEqual(self.api(admin,f'/api/clients/{lidl}/edit',{'first_name':'','last_name':''})['status'],400)
        self.assertEqual(self.api(admin,'/api/clients',{'first_name':'A','last_name':''})['id']>0,True)
        self.assertTrue(self.api(admin,'/api/backup').startswith(b'SQLite format 3'))

    def test_money_values(self):
        self.assertEqual(server.money('1.200,45'),120045)
        self.assertEqual(server.money('10.83'),1083)
        with self.assertRaises(ValueError):server.money('10,999')
        with self.assertRaises(ValueError):server.money('-1,00')


if __name__=='__main__': unittest.main(verbosity=2)