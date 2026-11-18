"""Customer may be created with money owed BY the centre, without moving cash."""
from http import cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime,timedelta,timezone
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server


class ImportedCustomerCredit(unittest.TestCase):
    def test_opening_credit_spent_and_withdrawn_remains_in_shared_book(self):
        previous=server.DB_PATH
        folder=tempfile.TemporaryDirectory()
        app=None
        thread=None
        try:
            server.DB_PATH=Path(folder.name)/'credit-initial.sqlite3'
            server.init_db()
            app=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=app.serve_forever,daemon=True)
            thread.start()
            url='http://127.0.0.1:'+str(app.server_address[1])

            def opener():
                return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar.CookieJar()))

            def api(user,endpoint,body=None):
                data=json.dumps(body).encode('utf-8') if body is not None else None
                req=urllib.request.Request(url+endpoint,data=data,
                    method='POST' if body is not None else 'GET',
                    headers={'Content-Type':'application/json'} if body is not None else {})
                try:
                    with user.open(req,timeout=6) as result:
                        return result.status,json.loads(result.read())
                except urllib.error.HTTPError as error:
                    return error.code,json.loads(error.read())

            guest,admin,staff=opener(),opener(),opener()
            self.assertEqual(api(guest,'/api/setup',{'full_name':'Responsabile','password':'TestPassword123!'})[0],201)
            self.assertEqual(api(admin,'/api/login',{'username':'admin','password':'TestPassword123!'})[0],200)
            self.assertEqual(api(admin,'/api/users',{'username':'operatore','full_name':'Operatore Due','password':'OperatorPass123!'})[0],201)
            self.assertEqual(api(staff,'/api/login',{'username':'operatore','password':'OperatorPass123!'})[0],200)
            s1=api(admin,'/api/shifts/open',{'cash':1,'initial':'800,00'})[1]['id']
            s2=api(staff,'/api/shifts/open',{'cash':2,'initial':'200,00'})[1]['id']
            self.assertEqual(api(admin,'/api/shifts/totals',{'shift_id':s1,'blue':'0'})[0],200)
            self.assertEqual(api(staff,'/api/shifts/totals',{'shift_id':s2,'blue':'0'})[0],200)

            older=(datetime.now(timezone.utc)-timedelta(days=15)).strftime('%Y-%m-%d')
            later=(datetime.now(timezone.utc)+timedelta(days=3)).strftime('%Y-%m-%d')
            self.assertEqual(api(admin,'/api/clients',{'first_name':'Futura','opening_position':'credit','opening_amount':'100,00','opening_date':later})[0],400)
            self.assertEqual(api(admin,'/api/clients',{'first_name':'Manca','opening_position':'credit','opening_amount':''})[0],400)
            self.assertEqual(api(admin,'/api/clients',{'first_name':'Errato','opening_position':'zero','opening_amount':'100'})[0],400)
            self.assertEqual(api(admin,'/api/clients',{'first_name':'Errato2','opening_position':'unknown','opening_amount':'100'})[0],400)
            self.assertEqual(api(admin,'/api/clients',{'first_name':'Debito','opening_position':'debt','opening_amount':'0'})[0],400)
            created=api(admin,'/api/clients',{'first_name':'LIDL','last_name':'','opening_position':'credit','opening_amount':'1.000,00','opening_date':older})
            self.assertEqual(created[0],201)
            cid=created[1]['id']
            customer=api(staff,'/api/clients')[1]['clients'][0]
            self.assertEqual(customer['credit_cents'],100000)
            self.assertEqual(customer['balance_cents'],100000)
            self.assertEqual(customer['debt_cents'],0)
            self.assertEqual(customer['opening_debt_cents'],0)
            self.assertEqual(customer['opening_credit_cents'],100000)
            self.assertFalse(customer['overdue'])
            self.assertIsNone(customer['first_unpaid_at'])
            self.assertEqual(api(admin,'/api/notifications')[1]['notifications'],[])
            self.assertEqual(api(admin,'/api/overview?cash=1')[1]['shift']['calculated_cents'],80000)
            self.assertEqual(api(staff,'/api/overview?cash=2')[1]['shift']['calculated_cents'],20000)
            self.assertEqual(api(admin,'/api/overview?cash=1')[1]['movements'],[])
            self.assertEqual(api(admin,'/api/clients',{'first_name':'LIDL','opening_position':'zero'})[0],409)

            self.assertEqual(api(admin,'/api/movements',{'shift_id':s1,'client_id':cid,'kind':'withdrawal','amount':'300,00'})[0],201)
            self.assertEqual(api(staff,'/api/clients')[1]['clients'][0]['balance_cents'],70000)
            self.assertEqual(api(admin,'/api/overview?cash=1')[1]['shift']['calculated_cents'],50000)

            self.assertEqual(api(staff,'/api/shifts/totals',{'shift_id':s2,'blue':'600,00'})[0],200)
            self.assertEqual(api(staff,'/api/movements',{'shift_id':s2,'client_id':cid,'kind':'debit','amount':'600,00'})[0],201)
            self.assertEqual(api(admin,'/api/clients')[1]['clients'][0]['credit_cents'],10000)
            self.assertEqual(api(staff,'/api/overview?cash=2')[1]['shift']['calculated_cents'],20000)

            self.assertEqual(api(admin,'/api/movements',{'shift_id':s1,'client_id':cid,'kind':'withdrawal','amount':'100,00'})[0],201)
            zero=api(staff,'/api/clients')[1]['clients']
            self.assertEqual(len(zero),1)
            self.assertEqual(zero[0]['first_name'],'LIDL')
            self.assertEqual(zero[0]['credit_cents'],0)
            self.assertEqual(zero[0]['balance_cents'],0)
            self.assertEqual(api(admin,'/api/overview?cash=1')[1]['shift']['calculated_cents'],40000)
            self.assertEqual(api(admin,'/api/shifts/close',{'shift_id':s1,'physical':'400,00'})[1]['difference_cents'],0)
            self.assertEqual(api(staff,'/api/shifts/close',{'shift_id':s2,'physical':'200,00'})[1]['difference_cents'],0)
            self.assertEqual(api(admin,'/api/clients/'+str(cid))[1]['client']['opening_credit_cents'],100000)

            # Legacy import-debt API still creates debt and the 7-day alert.
            debt=api(admin,'/api/clients',{'first_name':'Mario','last_name':'Rossi','opening_debt':'150,00','opening_debt_date':older})
            self.assertEqual(debt[0],201)
            self.assertEqual(api(admin,'/api/clients/'+str(debt[1]['id']))[1]['client']['debt_cents'],15000)
            self.assertEqual(len([n for n in api(admin,'/api/notifications')[1]['notifications'] if n['kind']=='overdue']),1)
            # No balance data is lost when the local DB initialisation runs twice.
            server.init_db()
            self.assertEqual(api(admin,'/api/clients/'+str(cid))[1]['client']['opening_credit_cents'],100000)
        finally:
            if app:
                app.shutdown()
                app.server_close()
            if thread:
                thread.join(timeout=3)
            server.DB_PATH=previous
            folder.cleanup()


if __name__=='__main__':
    unittest.main(verbosity=2)
