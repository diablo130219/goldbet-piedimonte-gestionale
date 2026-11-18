"""Regression: imported customer debt must not change today's cash accounts."""
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


class OpeningCustomerDebt(unittest.TestCase):
    def test_opening_debt_due_date_payment_and_both_tills(self):
        previous=server.DB_PATH
        temporary=tempfile.TemporaryDirectory()
        server_instance=None
        thread=None
        try:
            server.DB_PATH=Path(temporary.name)/'opening-debt.sqlite3'
            server.init_db()
            server_instance=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=server_instance.serve_forever,daemon=True)
            thread.start()
            url=f'http://127.0.0.1:{server_instance.server_address[1]}'

            def opener():
                return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar.CookieJar()))

            def api(user,route,data=None):
                body=json.dumps(data).encode('utf-8') if data is not None else None
                request=urllib.request.Request(url+route,data=body,
                    method='POST' if body is not None else 'GET',
                    headers={'Content-Type':'application/json'} if body is not None else {})
                try:
                    with user.open(request,timeout=6) as response:
                        return response.status,json.loads(response.read())
                except urllib.error.HTTPError as error:
                    return error.code,json.loads(error.read())

            guest,admin,staff=opener(),opener(),opener()
            self.assertEqual(api(guest,'/api/setup',{'full_name':'Responsabile','password':'AdminPassword123!'})[0],201)
            self.assertEqual(api(admin,'/api/login',{'username':'admin','password':'AdminPassword123!'})[0],200)
            self.assertEqual(api(admin,'/api/users',{'username':'staff','full_name':'Operatore Due','password':'OperatorPass123!'})[0],201)
            self.assertEqual(api(staff,'/api/login',{'username':'staff','password':'OperatorPass123!'})[0],200)
            s1=api(admin,'/api/shifts/open',{'cash':1,'initial':'100,00'})[1]['id']
            s2=api(staff,'/api/shifts/open',{'cash':2,'initial':'200,00'})[1]['id']
            self.assertEqual(api(admin,'/api/shifts/totals',{'shift_id':s1,'blue':'0'})[0],200)
            self.assertEqual(api(staff,'/api/shifts/totals',{'shift_id':s2,'blue':'0'})[0],200)
            old=(datetime.now(timezone.utc)-timedelta(days=9)).strftime('%Y-%m-%d')
            future=(datetime.now(timezone.utc)+timedelta(days=9)).strftime('%Y-%m-%d')
            invalid=api(admin,'/api/clients',{'first_name':'X','opening_debt':'1000','opening_debt_date':future})
            self.assertEqual(invalid[0],400)
            self.assertEqual(api(admin,'/api/clients',{
                'first_name':'Y','opening_debt_date':old})[0],400)
            self.assertEqual(api(admin,'/api/clients',{
                'first_name':'Z','opening_debt':'-1'})[0],400)
            created=api(admin,'/api/clients',{
                'first_name':'LIDL','last_name':'','opening_debt':'1.000,00','opening_debt_date':old})
            self.assertEqual(created[0],201)
            cid=created[1]['id']
            current=api(staff,'/api/clients')[1]['clients'][0]
            self.assertEqual(current['debt_cents'],100000)
            self.assertEqual(current['balance_cents'],-100000)
            self.assertEqual(current['opening_debt_cents'],100000)
            self.assertTrue(current['overdue'])
            self.assertEqual(current['days_open']>=8,True)
            self.assertEqual(len(api(admin,'/api/notifications')[1]['notifications']),1)
            self.assertEqual(api(admin,'/api/overview?cash=1')[1]['shift']['calculated_cents'],10000)
            self.assertEqual(api(staff,'/api/overview?cash=2')[1]['shift']['calculated_cents'],20000)
            self.assertEqual(api(admin,'/api/overview?cash=1')[1]['movements'],[])
            self.assertEqual(api(admin,'/api/clients',{
                'first_name':'LIDL','opening_debt':'200,00'})[0],409)
            self.assertEqual(len(api(staff,'/api/clients')[1]['clients']),1)

            self.assertEqual(api(staff,'/api/movements',{
                'shift_id':s2,'client_id':cid,'kind':'credit','amount':'200,00'})[0],201)
            partial=api(admin,'/api/clients')[1]['clients'][0]
            self.assertEqual(partial['balance_cents'],-80000)
            self.assertTrue(partial['overdue'])
            self.assertEqual(api(admin,'/api/overview?cash=1')[1]['shift']['entries_cents'],0)
            self.assertEqual(api(staff,'/api/overview?cash=2')[1]['shift']['entries_cents'],20000)

            self.assertEqual(api(staff,'/api/movements',{
                'shift_id':s2,'client_id':cid,'kind':'win','amount':'850,00'})[0],201)
            after=api(admin,'/api/clients')[1]['clients'][0]
            self.assertEqual(after['credit_cents'],5000)
            self.assertFalse(after['overdue'])
            self.assertIsNone(after['first_unpaid_at'])
            paid=[n for n in api(admin,'/api/notifications')[1]['notifications'] if n['kind']=='paid']
            self.assertEqual(len(paid),1)
            self.assertEqual(api(admin,'/api/clients/'+str(cid))[1]['client']['opening_debt_cents'],100000)
            self.assertEqual(api(admin,'/api/overview?cash=1')[1]['shift']['calculated_cents'],10000)
            self.assertEqual(api(staff,'/api/overview?cash=2')[1]['shift']['calculated_cents'],125000)
            # Move from +50 to zero; the customer remains in the shared address book.
            self.assertEqual(api(staff,'/api/movements',{
                'shift_id':s2,'client_id':cid,'kind':'withdrawal','amount':'50,00'})[0],201)
            at_zero=api(admin,'/api/clients')[1]['clients']
            self.assertEqual(len(at_zero),1)
            self.assertEqual(at_zero[0]['balance_cents'],0)
            self.assertEqual(at_zero[0]['first_name'],'LIDL')
            self.assertEqual(api(staff,'/api/overview?cash=2')[1]['shift']['calculated_cents'],120000)
            self.assertEqual(api(admin,'/api/shifts/close',{'shift_id':s1,'physical':'100,00'})[1]['difference_cents'],0)
        finally:
            if server_instance:
                server_instance.shutdown()
                server_instance.server_close()
            if thread:
                thread.join(timeout=3)
            server.DB_PATH=previous
            temporary.cleanup()


if __name__=='__main__':
    unittest.main(verbosity=2)
