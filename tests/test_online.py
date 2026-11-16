"""Minimal security checks for cloud deployment mode."""
import http.cookiejar
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class TestCloudSetup(unittest.TestCase):
    def test_token_required_then_setup_and_secure_login(self):
        before={k:os.environ.get(k) for k in ('GB_PUBLIC','GB_SETUP_TOKEN')}
        saved=server.DB_PATH
        temp=tempfile.TemporaryDirectory()
        http=None; thread=None
        try:
            os.environ['GB_PUBLIC']='1'
            os.environ['GB_SETUP_TOKEN']='this-is-a-long-private-setup-code-12345'
            server.DB_PATH=Path(temp.name)/'cloud-test.db'
            server.init_db()
            http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True); thread.start()
            base=f'http://127.0.0.1:{http.server_address[1]}'
            def req(path,body=None):
                data=json.dumps(body).encode() if body is not None else None
                r=urllib.request.Request(base+path, data=data, headers={'Content-Type':'application/json'} if data else {},method='POST' if data else 'GET')
                try:
                    with urllib.request.urlopen(r,timeout=5) as resp:
                        return resp.status,resp.headers, json.loads(resp.read())
                except urllib.error.HTTPError as ex:
                    return ex.code,ex.headers,json.loads(ex.read())
            self.assertEqual(req('/healthz')[0],200)
            self.assertTrue(req('/api/bootstrap')[2]['online_setup'])
            self.assertEqual(req('/api/setup',{'full_name':'Amministratore','password':'AsecretPass123!'})[0],403)
            self.assertEqual(req('/api/setup',{'full_name':'Amministratore','password':'AsecretPass123!','setup_token':'this-is-a-long-private-setup-code-12345'})[0],201)
            status,headers,_=req('/api/login',{'username':'admin','password':'AsecretPass123!'})
            self.assertEqual(status,200)
            self.assertIn('Secure',headers.get('Set-Cookie',''))
            self.assertEqual(req('/api/setup',{'full_name':'Bad','password':'AnotherSecret123!', 'setup_token':'this-is-a-long-private-setup-code-12345'})[0],409)
        finally:
            if http:
                http.shutdown();http.server_close()
            if thread:thread.join(timeout=3)
            server.DB_PATH=saved
            for k,v in before.items():
                if v is None:os.environ.pop(k,None)
                else:os.environ[k]=v
            temp.cleanup()

if __name__=='__main__':unittest.main()