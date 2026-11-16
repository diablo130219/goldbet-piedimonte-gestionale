"""Administrator test-data reset and single-field client names."""
from http import cookiejar
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class TestAdminReset(unittest.TestCase):
    def test_reset_requires_admin_confirmation_and_preserves_logins(self):
        original_path = server.DB_PATH
        temp = tempfile.TemporaryDirectory()
        http = None
        thread = None
        try:
            server.DB_PATH = Path(temp.name) / 'reset-test.sqlite3'
            server.init_db()
            http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{http.server_address[1]}'

            def opener():
                return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar.CookieJar()))

            def req(user, path, body=None):
                data = json.dumps(body).encode() if body is not None else None
                q = urllib.request.Request(base+path, data=data,
                    headers={'Content-Type': 'application/json'} if data else {},
                    method='POST' if data else 'GET')
                try:
                    with user.open(q, timeout=6) as r:
                        return r.status, json.loads(r.read())
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read())

            guest, admin, operator = opener(), opener(), opener()
            self.assertEqual(req(guest,'/api/setup',{'full_name':'Responsabile', 'password':'AdminPassword123!'})[0],201)
            self.assertEqual(req(admin,'/api/login',{'username':'admin','password':'AdminPassword123!'})[0],200)
            self.assertEqual(req(admin,'/api/users',{'username':'operator01','full_name':'Operatore Uno','password':'OperatorPass123!'})[0],201)
            self.assertEqual(req(operator,'/api/login',{'username':'operator01','password':'OperatorPass123!'})[0],200)
            shift1=req(admin,'/api/shifts/open',{'cash':1,'initial':'325,25'})[1]['id']
            shift2=req(operator,'/api/shifts/open',{'cash':2,'initial':'500,00'})[1]['id']
            self.assertEqual(req(admin,'/api/shifts/totals',{'shift_id':shift1,'green':'100,00','red':'10,00'})[0],200)
            self.assertEqual(req(operator,'/api/shifts/totals',{'shift_id':shift2,'green':'50,00','red':'0'})[0],200)

            self.assertEqual(req(admin,'/api/clients',{'first_name':'  ', 'last_name':'   '})[0],400)
            lidl=req(admin,'/api/clients',{'first_name':'LIDL', 'last_name':''})
            self.assertEqual(lidl[0],201)
            lidl_id=lidl[1]['id']
            surname=req(operator,'/api/clients',{'first_name':'', 'last_name':'Bianchi'})
            self.assertEqual(surname[0],201)
            self.assertEqual(req(admin,'/api/clients',{'first_name':'LIDL', 'last_name':''})[0],409)
            names=[(x['first_name'],x['last_name']) for x in req(operator,'/api/clients')[1]['clients']]
            self.assertEqual(names,[('','Bianchi'),('LIDL','')])
            self.assertEqual(req(admin,'/api/movements',{'shift_id':shift1,'client_id':lidl_id,'kind':'debit','amount':'42,00'})[0],201)
            self.assertEqual(req(admin,'/api/shifts/close',{'shift_id':shift1,'physical':'373,25'})[0],200)

            wrong_phrase=req(admin,'/api/admin/reset-data',{'confirmation':'SÌ','password':'AdminPassword123!'})
            self.assertEqual(wrong_phrase[0],400)
            wrong_password=req(admin,'/api/admin/reset-data',{'confirmation':'AZZERA TUTTO','password':'wrongpassword'})
            self.assertEqual(wrong_password[0],403)
            unauthorized=req(operator,'/api/admin/reset-data',{'confirmation':'AZZERA TUTTO','password':'OperatorPass123!'})
            self.assertEqual(unauthorized[0],403)
            self.assertEqual(len(req(admin,'/api/clients')[1]['clients']),2)
            result=req(admin,'/api/admin/reset-data',{'confirmation':'AZZERA TUTTO','password':'AdminPassword123!'})
            self.assertEqual(result[0],200)
            self.assertEqual(result[1]['deleted']['clients'],2)
            self.assertEqual(result[1]['deleted']['shifts'],2)
            self.assertEqual(result[1]['deleted']['movements'],1)
            self.assertEqual(req(operator,'/api/clients')[1]['clients'],[])
            self.assertIsNone(req(operator,'/api/overview?cash=2')[1]['shift'])
            self.assertIsNone(req(admin,'/api/overview?cash=1')[1]['shift'])
            self.assertEqual(req(admin,'/api/shifts/archive?cash=1')[1]['shifts'],[])
            self.assertEqual(req(admin,'/api/notifications')[1]['notifications'],[])
            self.assertEqual(len(req(admin,'/api/users')[1]['users']),2)
            with server.db_session() as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM audit').fetchone()['n'],1)
            self.assertEqual(req(operator,'/api/me')[0],200)
            self.assertEqual(req(admin,'/api/shifts/open',{'cash':1,'initial':'100,00'})[0],201)
        finally:
            if http:
                http.shutdown()
                http.server_close()
            if thread:
                thread.join(timeout=3)
            server.DB_PATH=original_path
            temp.cleanup()


if __name__ == '__main__':
    unittest.main()