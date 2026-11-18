"""Client balances can be negative, positive, or zero without losing saved people."""
from http import cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from sys import path

path.insert(0,str(Path(__file__).resolve().parents[1]))
import server


class ClientWalletFlows(unittest.TestCase):
    def test_winnings_bets_withdrawals_zero_and_cash_reconciliation(self):
        original=server.DB_PATH
        folder=tempfile.TemporaryDirectory()
        http=None
        thread=None
        try:
            server.DB_PATH=Path(folder.name)/'wallet-test.sqlite3'
            server.init_db()
            http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True)
            thread.start()
            base='http://127.0.0.1:'+str(http.server_address[1])

            def client():
                return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar.CookieJar()))

            def api(opener,resource,body=None):
                payload=json.dumps(body).encode() if body is not None else None
                request=urllib.request.Request(base+resource,data=payload,
                    method='POST' if body is not None else 'GET',
                    headers={'Content-Type':'application/json'} if body is not None else {})
                try:
                    with opener.open(request,timeout=5) as response:
                        return response.status,json.loads(response.read())
                except urllib.error.HTTPError as error:
                    return error.code,json.loads(error.read())

            guest,admin,other=client(),client(),client()
            self.assertEqual(api(guest,'/api/setup',{'full_name':'Responsabile','password':'Amministratore123!'})[0],201)
            self.assertEqual(api(admin,'/api/login',{'username':'admin','password':'Amministratore123!'})[0],200)
            self.assertEqual(api(admin,'/api/users',{'username':'operatore','full_name':'Operatore Due','password':'OperatoreSegreta123!'})[0],201)
            self.assertEqual(api(other,'/api/login',{'username':'operatore','password':'OperatoreSegreta123!'})[0],200)
            first=api(admin,'/api/shifts/open',{'cash':1,'initial':'200,00'})[1]['id']
            second=api(other,'/api/shifts/open',{'cash':2,'initial':'500,00'})[1]['id']
            customer=api(admin,'/api/clients',{'first_name':'LIDL','last_name':''})[1]['id']
            # The terminal produced 1,000€ of bets and 2,000€ of winnings,
            # hence the blue is -1,000€. The winnings stay on the customer's balance.
            self.assertEqual(api(admin,'/api/shifts/totals',{'shift_id':first,'blue':'-1000,00'})[0],200)
            debit=api(admin,'/api/movements',{'shift_id':first,'client_id':customer,'kind':'debit','amount':'1000,00'})
            self.assertEqual(debit[0],201)
            c1=api(other,'/api/clients')[1]['clients'][0]
            self.assertEqual(c1['balance_cents'],-100000)
            self.assertEqual(c1['debt_cents'],100000)
            self.assertEqual(c1['credit_cents'],0)
            win=api(admin,'/api/movements',{'shift_id':first,'client_id':customer,'kind':'win','amount':'2000,00'})
            self.assertEqual(win[0],201)
            c2=api(other,'/api/clients')[1]['clients'][0]
            self.assertEqual(c2['balance_cents'],100000)
            self.assertEqual(c2['credit_cents'],100000)
            self.assertEqual(c2['debt_cents'],0)
            self.assertIsNone(c2['first_unpaid_at'])
            self.assertFalse(c2['overdue'])
            self.assertEqual(len([a for a in api(admin,'/api/notifications')[1]['notifications'] if a['kind']=='paid']),1)
            # First cash till: 200 opening + (-1,000) blue -1,000 unpaid bet +2,000
            # winnings retained rather than handed over = 200€ physically present.
            p1=api(admin,'/api/overview?cash=1')[1]['shift']
            self.assertEqual(p1['winnings_held_cents'],200000)
            self.assertEqual(p1['exits_cents'],100000)
            self.assertEqual(p1['calculated_cents'],20000)

            # The customer bets 300€ from their positive balance on the other till.
            self.assertEqual(api(other,'/api/shifts/totals',{'shift_id':second,'blue':'300,00'})[0],200)
            self.assertEqual(api(other,'/api/movements',{'shift_id':second,'client_id':customer,'kind':'debit','amount':'300,00'})[0],201)
            self.assertEqual(api(admin,'/api/clients')[1]['clients'][0]['balance_cents'],70000)
            withdrawal=api(other,'/api/movements',{'shift_id':second,'client_id':customer,'kind':'withdrawal','amount':'400,00'})
            self.assertEqual(withdrawal[0],201)
            self.assertEqual(api(admin,'/api/clients')[1]['clients'][0]['credit_cents'],30000)
            self.assertEqual(api(other,'/api/movements',{'shift_id':second,'client_id':customer,'kind':'withdrawal','amount':'300,01'})[0],400)
            # An earlier win cannot be voided once a later withdrawal uses the credit.
            self.assertEqual(api(admin,'/api/movements/'+str(win[1]['id'])+'/void',{'reason':'Provare annullamento'})[0],409)
            self.assertEqual(api(other,'/api/overview?cash=2')[1]['shift']['calculated_cents'],10000)
            self.assertEqual(api(other,'/api/movements',{'shift_id':second,'client_id':customer,'kind':'withdrawal','amount':'300,00'})[0],201)
            # Customer stays in the common directory at zero. No re-creation.
            zero=api(admin,'/api/clients')[1]['clients']
            self.assertEqual(len(zero),1)
            self.assertEqual(zero[0]['first_name'],'LIDL')
            self.assertEqual(zero[0]['balance_cents'],0)
            self.assertEqual(zero[0]['debt_cents'],0)
            self.assertEqual(zero[0]['credit_cents'],0)
            self.assertEqual(api(other,'/api/clients',{'first_name':'LIDL','last_name':''})[0],409)
            self.assertEqual(api(other,'/api/overview?cash=2')[1]['shift']['calculated_cents'],-20000)
            self.assertEqual(api(admin,'/api/shifts/close',{'shift_id':first,'physical':'200,00'})[1]['difference_cents'],0)
            # The second till would need an actual cash draw/top-up to pay 700€;
            # a negative expected amount correctly exposes insufficient funds.
            self.assertEqual(api(other,'/api/shifts/close',{'shift_id':second,'physical':'0'})[1]['difference_cents'],-20000)
            self.assertEqual(len(api(admin,'/api/shifts/'+str(first))[1]['movements']),2)
            self.assertEqual(len(api(other,'/api/shifts/'+str(second))[1]['movements']),3)
        finally:
            if http:
                http.shutdown()
                http.server_close()
            if thread:
                thread.join(timeout=3)
            server.DB_PATH=original
            folder.cleanup()


if __name__=='__main__':
    unittest.main(verbosity=2)
