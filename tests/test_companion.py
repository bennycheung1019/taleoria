import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from kobold_rpg.campaign import blank_campaign
from kobold_rpg.companion import load_config,with_companion
from kobold_rpg.engine import Engine
from kobold_rpg.library import CampaignLibrary
from server import make_handler

class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'companion.json';self.config=load_config(self.path)
        self.config['allowed_origins']=['https://taleoria.example']
        e=Engine(Path(self.tmp.name)/'game.sqlite3',seed=blank_campaign());self.lib=CampaignLibrary(Path(self.tmp.name)/'library',e)
        self.saved=[]
        handler=make_handler(e,'http://127.0.0.1:5001','internal-token',self.lib,save_connection=self.saved.append)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),with_companion(handler,'internal-token',self.config,self.path))
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
    def request(self,path='/api/session',method='GET',body=None,**headers):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        data=None if body is None else json.dumps(body)
        c.request(method,path,body=data,headers={'Host':'remote.trycloudflare.com','Origin':'https://taleoria.example',**headers})
        r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result
    def remote(self,**extra):return {'X-Taleoria-Key':self.config['key'],**extra}
    def test_tunnel_does_not_expose_html_token_or_unpaired_state(self):
        for path in ('/','/api/session','/api/history','/api/state','/app.js'):
            code,headers,data=self.request(path)
            self.assertEqual(code,401);self.assertNotIn(b'internal-token',data)
    def test_valid_key_reads_session_and_keeps_private_gm_routes_closed(self):
        code,headers,data=self.request(**self.remote());self.assertEqual(code,200)
        self.assertTrue(json.loads(data)['state']['setup_required'])
        self.assertEqual(headers['Access-Control-Allow-Origin'],'https://taleoria.example')
        for path in ('/api/export','/api/gm/npcs','/api/companion/pairing','/'):
            self.assertEqual(self.request(path,**self.remote())[0],404)
    def test_wrong_origin_is_denied_even_with_key(self):
        code,headers,data=self.request(**self.remote(Origin='https://attacker.example'))
        self.assertEqual(code,403);self.assertNotIn('Access-Control-Allow-Origin',headers)
    def test_preflight_only_allows_explicit_origin_methods_and_headers(self):
        headers={'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'Content-Type,X-Taleoria-Key,X-RPG-Token,X-RPG-Session,Prefer'}
        self.assertEqual(self.request(method='OPTIONS',**headers)[0],204)
        self.assertEqual(self.request(method='OPTIONS',**{**headers,'Origin':'https://attacker.example'})[0],403)
        self.assertEqual(self.request(method='OPTIONS',**{**headers,'Access-Control-Request-Headers':'cookie'})[0],403)
    def test_local_pairing_requires_local_token_and_persists_origin(self):
        local={'Host':'127.0.0.1','Origin':'http://127.0.0.1','X-RPG-Token':'internal-token'}
        self.assertEqual(self.request('/api/companion/pairing',Host='localhost',Origin='')[0],403)
        code,_,data=self.request('/api/companion/pairing',**local);self.assertEqual(code,200)
        self.assertEqual(json.loads(data)['key'],self.config['key'])
        code,_,_=self.request('/api/companion/pairing','POST',{'website':'https://new.vercel.app'},**local)
        self.assertEqual(code,200);self.assertIn('https://new.vercel.app',load_config(self.path)['allowed_origins'])
    def test_tunnel_cannot_spoof_local_pairing_by_forwarding_local_host(self):
        self.assertEqual(self.request('/api/companion/pairing',Host='localhost',**{'CF-Connecting-IP':'1.2.3.4','X-RPG-Token':'internal-token'})[0],401)
    def test_different_local_ports_are_cross_origin_and_do_not_bypass_pairing(self):
        code,_,_=self.request(Host='127.0.0.1:8787',Origin='http://127.0.0.1:9999')
        self.assertEqual(code,403)
    def test_model_endpoint_edit_is_persisted_without_restarting_and_rejects_external_targets(self):
        session=self.lib.session_id
        with patch('server.urllib.request.urlopen',side_effect=OSError('offline')):
            code,_,_=self.request('/api/connection/settings','POST',{'session_id':session,'model_url':'http://127.0.0.1:5002'},**self.remote())
            self.assertEqual(code,200);self.assertEqual(self.saved,['http://127.0.0.1:5002'])
            code,_,data=self.request('/api/connection',**self.remote());self.assertEqual(json.loads(data)['model_url'],'http://127.0.0.1:5002')
        self.assertEqual(self.request('/api/connection/settings','POST',{'session_id':session,'model_url':'https://arbitrary.example'},**self.remote())[0],400)
    def test_pairing_file_is_private_and_survives_restart(self):
        self.assertEqual(self.path.stat().st_mode&0o077,0)
        self.assertEqual(load_config(self.path)['key'],self.config['key'])

if __name__=='__main__':unittest.main()
