"""End-to-end tests: non-client entries do not touch the rubrica or cross tills."""
import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class NonClientCashMovements(unittest.TestCase):
    def test_separate_cash_entries_and_close(self):
        original_path=server.DB_PATH
        temp=tempfile.TemporaryDirectory()
        http=None
        thread=None
        try:
            server.DB_PATH=Path(temp.name)/'cash-adjustments.sqlite3'
            server.init_db()
            http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True)
            thread.start()
            url=f'http://127.0.0.1:{http.server_address[1]}'

            def opener():
                return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

            def call(user,path,payload=None):
                data=json.dumps(payload).encode('utf-8') if payload is not None else None
                request=urllib.request.Request(
                    url+path,data=data,method='POST' if payload is not None else 'GET',
                    headers={'Content-Type':'application/json'} if payload is not None else {})
                try:
                    with user.open(request,timeout=6) as response:
                        return response.status,json.loads(response.read())
                except urllib.error.HTTPError as error:
                    return error.code,json.loads(error.read())

            guest,admin,staff=opener(),opener(),opener()
            self.assertEqual(call(guest,'/api/setup',{'full_name':'Responsabile','password':'TestPassword123!'})[0],201)
            self.assertEqual(call(admin,'/api/login',{'username':'admin','password':'TestPassword123!'})[0],200)
            self.assertEqual(call(admin,'/api/users',{'username':'operatore','full_name':'Operatore Due','password':'OperatorPass123!'})[0],201)
            self.assertEqual(call(staff,'/api/login',{'username':'operatore','password':'OperatorPass123!'})[0],200)
            till1=call(admin,'/api/shifts/open',{'cash':1,'initial':'50,00'})[1]['id']
            till2=call(staff,'/api/shifts/open',{'cash':2,'initial':'20,00'})[1]['id']
            self.assertEqual(call(admin,'/api/shifts/totals',{'shift_id':till1,'blue':'100,00'})[0],200)
            self.assertEqual(call(staff,'/api/shifts/totals',{'shift_id':till2,'blue':'200,00'})[0],200)
            client=call(admin,'/api/clients',{'first_name':'Mario','last_name':'Rossi'})[1]['id']
            call(admin,'/api/movements',{'shift_id':till1,'client_id':client,'kind':'debit','amount':'10,00'})
            n_clients=len(call(admin,'/api/clients')[1]['clients'])
            self.assertEqual(n_clients,1)

            deposit=call(admin,'/api/cash-adjustments',{
                'shift_id':till1,'label':'Prelievo dalla cassaforte',
                'direction':'in','amount':'100,00','note':'Contanti portati in cassa'})
            self.assertEqual(deposit[0],201)
            coffee=call(admin,'/api/cash-adjustments',{
                'shift_id':till1,'label':'Caffè','direction':'out','amount':'5,00'})
            self.assertEqual(coffee[0],201)
            self.assertEqual(call(staff,'/api/cash-adjustments',{
                'shift_id':till1,'label':'Altro','direction':'in','amount':'1,00'})[0],403)
            self.assertEqual(call(admin,'/api/cash-adjustments',{
                'shift_id':till1,'label':'  ','direction':'in','amount':'1,00'})[0],400)
            self.assertEqual(call(admin,'/api/cash-adjustments',{
                'shift_id':till1,'label':'Caffè','direction':'wrong','amount':'1,00'})[0],400)

            one=call(admin,'/api/overview?cash=1')[1]
            two=call(staff,'/api/overview?cash=2')[1]
            self.assertEqual(one['shift']['other_in_cents'],10000)
            self.assertEqual(one['shift']['other_out_cents'],500)
            self.assertEqual(one['shift']['calculated_cents'],23500)
            self.assertEqual(len(one['adjustments']),2)
            self.assertEqual(one['adjustments'][0]['operator_name'],'Responsabile')
            self.assertEqual(two['shift']['calculated_cents'],22000)
            self.assertEqual(two['adjustments'],[])
            self.assertEqual(call(staff,'/api/clients')[1]['clients'][0]['debt_cents'],1000)
            self.assertEqual(len(call(staff,'/api/clients')[1]['clients']),n_clients)
            self.assertEqual(call(admin,'/api/notifications')[1]['notifications'],[])

            self.assertEqual(call(admin,'/api/cash-adjustments/'+str(coffee[1]['id'])+'/void',
                                  {'reason':'Spesa annullata'})[0],200)
            self.assertEqual(call(admin,'/api/overview?cash=1')[1]['shift']['calculated_cents'],24000)
            self.assertEqual(call(admin,'/api/cash-adjustments/'+str(coffee[1]['id'])+'/void',
                                  {'reason':'Ancora'})[0],409)
            self.assertEqual(call(admin,'/api/cash-adjustments',{
                'shift_id':till1,'label':'Errore bolletta','direction':'out','amount':'5,00'})[0],201)
            self.assertEqual(call(admin,'/api/shifts/close',
                                  {'shift_id':till1,'physical':'235,00'})[1]['difference_cents'],0)
            self.assertEqual(call(admin,'/api/cash-adjustments',{
                'shift_id':till1,'label':'Caffè','direction':'out','amount':'1,00'})[0],409)
            archived=call(admin,'/api/shifts/'+str(till1))[1]
            self.assertEqual(archived['shift']['other_in_cents'],10000)
            self.assertEqual(archived['shift']['other_out_cents'],500)
            self.assertEqual(len(archived['adjustments']),3)
            self.assertEqual(len(archived['movements']),1)
            self.assertIn('cash_adjustments',server.postgres_backup.__code__.co_consts.__str__())
            result=call(admin,'/api/admin/reset-data',{
                'confirmation':'AZZERA TUTTO','password':'TestPassword123!'})
            self.assertEqual(result[0],200)
            self.assertEqual(result[1]['deleted']['cash_adjustments'],3)
            self.assertEqual(call(admin,'/api/clients')[1]['clients'],[])
            self.assertEqual(call(admin,'/api/shifts/archive?cash=1')[1]['shifts'],[])
        finally:
            if http:
                http.shutdown()
                http.server_close()
            if thread:
                thread.join(timeout=3)
            server.DB_PATH=original_path
            temp.cleanup()


if __name__=='__main__':
    unittest.main(verbosity=2)
