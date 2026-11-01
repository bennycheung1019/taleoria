import copy
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from kobold_rpg.progress import Progress,ProgressStore,active,stage
from kobold_rpg.model import _complete
from kobold_rpg.names import aliases,display
from kobold_rpg.campaign import new_campaign
from kobold_rpg.worldgen import generate_world
from test_library import fixture


class ProgressTests(unittest.TestCase):
    def test_estimates_advance_by_actual_stream_and_only_finish_at_100(self):
        job=Progress(2)
        with stage('裁定'):job.begin(10,[{'content':'提示'}],{'last_process_speed':100,'last_eval_speed':5})
        first=job.snapshot();self.assertTrue(first['estimated']);self.assertLess(first['percent'],100)
        for _ in range(5):job.fragment()
        middle=job.snapshot();self.assertGreater(middle['percent'],first['percent'])
        job.call_done();self.assertEqual(job.snapshot()['percent'],50)
        job.finish(False);self.assertNotEqual(job.snapshot()['percent'],100)
        job.finish(True);self.assertEqual(job.snapshot()['percent'],100)

    def test_old_private_text_cannot_appear_in_progress_and_sessions_are_separate(self):
        store=ProgressStore();store.start('one','request',2)
        self.assertEqual(store.snapshot('two','request')['status'],'waiting')
        self.assertNotIn('text',store.snapshot('one','request'))

    def test_stream_completion_consumes_fragments_without_publishing_prose(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                data=json.dumps({'last_eval_speed':10,'last_process_speed':100}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert body['stream'] is True
                assert body['chat_template_kwargs']['enable_thinking'] is False
                assert body['reasoning_effort']=='none'
                parts=['{"answer":','"秘密草案"','}']
                data=''.join('data: '+json.dumps({'choices':[{'delta':{'content':part},'finish_reason':None}]})+'\n\n' for part in parts)+'data: [DONE]\n\n'
                data=data.encode();self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever);thread.start()
        job=Progress(1);token=active.set(job)
        try:
            result=_complete([{'role':'user','content':'測試'}],f'http://127.0.0.1:{server.server_port}',100,.2)
            self.assertEqual(result,{'answer':'秘密草案'});self.assertEqual(job.fragments,3)
            self.assertNotIn('秘密草案',json.dumps(job.snapshot()))
        finally:active.reset(token);server.shutdown();server.server_close();thread.join()


class NameTests(unittest.TestCase):
    def test_display_is_idempotent_preserves_ids_and_does_not_change_shift_word(self):
        state=new_campaign();registry=aliases(state)
        item={'name':'霧橋鎮北門','description':'班站在北門。哈克正在交班。','location':'gate'}
        result=display(item,registry)
        self.assertIn('班（Ben）',result['description']);self.assertIn('哈克（Hark）',result['description'])
        self.assertIn('交班。',result['description']);self.assertEqual(result['location'],'gate')
        self.assertEqual(display(result,registry),result);self.assertEqual(item['name'],'霧橋鎮北門')

    def test_missing_english_names_are_repaired_without_renaming_chinese_identity(self):
        candidate=fixture();plan=copy.deepcopy(candidate['plan']);plan['npc']['name']='小禾'
        with patch('kobold_rpg.worldgen._complete',side_effect=[plan,{'npc':'Xiao He'}]):
            result=generate_world(candidate['preferences'],'http://local')
        self.assertEqual(result['plan']['npc']['name'],'小禾（Xiao He）')
        self.assertEqual(result['seed']['pc']['name'],'阿晴（Ah Ching）')


if __name__=='__main__':unittest.main()
