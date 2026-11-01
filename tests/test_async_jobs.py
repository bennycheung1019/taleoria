import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from kobold_rpg.engine import Engine, RuleError
from kobold_rpg.campaign import new_campaign
from kobold_rpg.library import CampaignLibrary
from server import make_handler
from test_library import fixture


class AsyncGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.engine=Engine(Path(self.tmp.name)/'world.db',seed=new_campaign())
        self.library=CampaignLibrary(Path(self.tmp.name)/'library',self.engine)
        self.fake_gm=lambda *args,**kwargs: {'narration':'你看見雨中的城門。','changes':{}}
        self.handler=make_handler(self.engine,'http://127.0.0.1:5001','test',self.library,gm=lambda *args,**kwargs:self.fake_gm(*args,**kwargs))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),self.handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.handler.jobs.join();self.handler.illustrations.join()
        self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,method,path,body=None,session=None,token='test',disconnect=False):
        session=session or self.library.session_id
        if body is not None:body={**body,'session_id':session}
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            conn.request(method,path,body=json.dumps(body) if body is not None else None,
                         headers={'Content-Type':'application/json','X-RPG-Token':token,
                                  'X-RPG-Session':session,'Prefer':'respond-async'})
            if disconnect:return
            response=conn.getresponse();data=response.read()
            return response.status,json.loads(data) if 'application/json' in response.getheader('Content-Type','') else data.decode()
        finally:conn.close()

    def result(self,request='turn'):
        return self.request('GET','/api/jobs?request_id='+request)

    def test_navigation_reload_and_disconnected_client_commit_exactly_once(self):
        started=threading.Event();release=threading.Event()
        proposal={'narration':'哈克說：「你好。」','changes':{}}
        def generating(*args,**kwargs):
            started.set();release.wait(3);return proposal
        body={'text':'我問哈克：「你好嗎？」','revision':0,'request_id':'turn'}
        with patch.object(self,'fake_gm',side_effect=generating) as model:
            try:
                # Close the original connection before even reading its reply.
                self.request('POST','/api/play',body,disconnect=True)
                self.assertTrue(started.wait(1))
                self.assertEqual(self.request('GET','/')[0],200)
                self.assertEqual(self.request('GET','/api/session')[1]['state']['revision'],0)
                self.assertEqual(self.result()[1]['status'],'running')
                # A page reload sends the same identifier and attaches, not rerolls.
                self.assertEqual(self.request('POST','/api/play',body)[0],202)
                self.assertEqual(self.engine.state()['revision'],0)
            finally:release.set();self.handler.jobs.join()
            self.assertEqual(self.result()[1]['status'],'done')
            result=self.result()[1]['result'];self.assertIn('你好',result['turn']['narration'])
            self.handler.illustrations.join();before=self.engine.state()
            self.assertEqual(self.request('POST','/api/play',body)[0],202)
            self.assertEqual(self.result()[1]['result'],result)
            self.assertEqual(model.call_count,1);self.assertEqual(self.engine.state(),before)
            self.assertEqual(len([r for r in self.engine.history() if r['status']=='approved']),1)

    def test_failed_model_json_is_retained_without_retry_or_world_change(self):
        body={'text':'我問哈克：「你好嗎？」','revision':0,'request_id':'turn'}
        with patch.object(self,'fake_gm',side_effect=RuleError('模型沒有回傳可驗證的 JSON。')) as model:
            self.assertEqual(self.request('POST','/api/play',body)[0],202);self.handler.jobs.join()
            self.assertEqual(self.result()[1]['status'],'error')
            self.assertIn('JSON',self.result()[1]['result']['error'])
            self.assertEqual(self.request('POST','/api/play',body)[0],202)
            self.assertEqual(model.call_count,1);self.assertEqual(self.engine.state()['revision'],0)

    def test_world_preview_survives_navigation_without_switching_campaign(self):
        body={'preferences':fixture()['preferences'],'request_id':'world'}
        before=self.engine.state()
        with patch('server.generate_world',return_value=fixture()) as model:
            self.assertEqual(self.request('POST','/api/world/draft',body)[0],202);self.handler.jobs.join()
            self.assertEqual(self.request('GET','/api/session')[0],200)
            result=self.result('world')[1]['result'];self.assertIn('preview_id',result)
            self.assertEqual(self.request('POST','/api/world/draft',body)[0],202)
            self.assertEqual(self.result('world')[1]['result']['preview_id'],result['preview_id'])
            self.assertEqual(model.call_count,1);self.assertEqual(self.engine.state(),before)

    def test_job_results_require_token_and_matching_session(self):
        body={'text':'環顧四周','revision':0,'request_id':'turn'}
        self.assertEqual(self.request('POST','/api/play',body)[0],202);self.handler.jobs.join()
        self.assertEqual(self.result()[0],200)
        self.assertEqual(self.request('GET','/api/jobs?request_id=turn',session='other')[0],404)
        self.assertEqual(self.request('GET','/api/jobs?request_id=turn',token='wrong')[0],404)
        self.assertEqual(self.request('POST','/api/play',body,session='stale')[0],400)

    def test_request_identifier_cannot_be_reused_for_another_action(self):
        body={'text':'環顧四周','revision':0,'request_id':'turn'}
        self.request('POST','/api/play',body);self.handler.jobs.join();before=self.engine.state()
        self.assertEqual(self.request('POST','/api/play',{**body,'text':'查看背包'})[0],400)
        self.assertEqual(self.engine.state(),before)

    def test_second_request_is_not_queued_behind_unfinished_generation(self):
        started=threading.Event();release=threading.Event()
        def generating(*args,**kwargs):started.set();release.wait(3);return fixture()
        body={'preferences':fixture()['preferences'],'request_id':'world'}
        with patch('server.generate_world',side_effect=generating) as model:
            try:
                self.request('POST','/api/world/draft',body);self.assertTrue(started.wait(1))
                self.assertEqual(self.request('POST','/api/world/draft',{**body,'request_id':'another'})[0],400)
            finally:release.set();self.handler.jobs.join()
            self.assertEqual(model.call_count,1)


if __name__=='__main__':unittest.main()
