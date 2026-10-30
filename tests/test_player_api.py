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
from kobold_rpg.canon import digest
from server import make_handler
from test_library import fixture


class PlayerAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.engine=Engine(Path(self.tmp.name)/'world.db',seed=new_campaign())
        self.library=CampaignLibrary(Path(self.tmp.name)/'library',self.engine)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.engine,'http://127.0.0.1:5001','test-token',self.library,enricher=lambda *args: [],planner=None,gm=None))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.server.RequestHandlerClass.background.join()

    def request(self,method,path,body=None,session=None,token='test-token'):
        if body is not None:body={**body,'session_id':session or self.library.session_id}
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            conn.request(method,path,body=json.dumps(body) if body is not None else None,
                         headers={'Content-Type':'application/json','X-RPG-Token':token,
                                  'X-RPG-Session':session or self.library.session_id})
            response=conn.getresponse();data=response.read()
            return response.status,json.loads(data)
        finally:conn.close()

    def test_world_preview_confirmation_and_stale_session_boundary(self):
        before=self.engine.state();old_session=self.library.session_id
        with patch('server.generate_world',return_value=fixture()):
            code,preview=self.request('POST','/api/world/draft',{'preferences':fixture()['preferences']})
        self.assertEqual(code,200);self.assertEqual(self.library.engine.state(),before)
        code,_=self.request('POST','/api/world/create',{'preview_id':preview['preview_id']})
        self.assertEqual(code,200);self.assertEqual(self.library.engine.state()['pc']['name'],'阿晴（Ah Ching）')
        code,_=self.request('POST','/api/play',{'text':'環顧四周','revision':1,'request_id':'stale'},session=old_session)
        self.assertEqual(code,400);self.assertEqual(self.library.engine.state()['revision'],1)

    def test_save_load_roundtrip_through_player_endpoints(self):
        code,saved=self.request('POST','/api/save',{'name':'啟程之前'})
        self.assertEqual(code,200)
        code,data=self.request('GET','/api/library')
        self.assertEqual(data['saves'][0]['name'],'啟程之前')
        self.assertNotIn('path',data['saves'][0])
        code,_=self.request('POST','/api/load',{'kind':'save','id':saved['id']})
        self.assertEqual(code,200)
        code,session=self.request('GET','/api/session')
        self.assertEqual(code,200);self.assertEqual(session['state']['revision'],0)
        self.assertNotIn('canon',session['state']);self.assertEqual(session['history'],[])

    def test_one_send_commits_checked_response_once_without_player_preview(self):
        proposal={'outcome':'success','reason':'私人裁定說明不出現在玩家記事。','narration':'哈克點頭，回應你的問候。','events':[]}
        audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
        with patch('server.react',return_value=proposal),patch('server.audit_narration',return_value=audit):
            code,result=self.request('POST','/api/play',{'text':'我問哈克：「你好嗎？」','revision':0,'request_id':'play'})
        self.assertEqual(code,200);self.assertEqual(result['status'],'approved');self.assertEqual(self.engine.state()['revision'],1)
        with patch('server.react',side_effect=AssertionError('must not generate twice')):
            code,again=self.request('POST','/api/play',{'text':'我問哈克：「你好嗎？」','revision':0,'request_id':'play'})
        self.assertEqual(code,200);self.assertEqual(again['revision'],1);self.assertEqual(self.engine.state()['revision'],1)
        _,history=self.request('GET','/api/history')
        self.assertEqual(history[0]['declaration'],'我問哈克（Hark）：「你好嗎？」');self.assertNotIn('reason',history[0])
        self.assertEqual(self.engine.history()[0]['action']['text'],'我問哈克：「你好嗎？」')

    def test_check_out_anya_at_river_street_is_delivered_without_moving_either_character(self):
        code, travel = self.request('POST','/api/play',{'text':'我前往河街。','revision':0,'request_id':'river-arrival'})
        self.assertEqual(code,200)
        before=self.engine.state()
        proposal={'outcome':'success','reason':'以河街已知景象觀察遠處。',
                  'narration':'你看向渡口的安雅（Anya），她仍在整理繫船索；這裡看不清更多細節。','events':[]}
        verdict={'supported':True,'actors':['ben','anya'],'powers':[],'issues':[]}
        with patch('kobold_rpg.model._complete',side_effect=AssertionError('simple observation needs no generation')) as complete:
            code,result=self.request('POST','/api/play',{'text':'check out Anya','revision':before['revision'],'request_id':'look-at-anya'})
        self.assertEqual(code,200)
        self.assertEqual(result['status'],'routine')
        self.assertIn('安雅（Anya）正在整理繫船索',result['narration'])
        self.assertIn('無法確認更多細節',result['narration'])
        complete.assert_not_called()
        self.assertEqual(self.engine.state()['pc']['location'],'river_street')
        self.assertEqual(self.engine.state()['npcs']['anya'],before['npcs']['anya'])
        self.assertEqual(self.engine.history()[-1]['action']['text'],'check out Anya')
        self.assertTrue(self.engine.verify())

    def test_get_closer_to_known_anya_moves_once_without_any_model_call(self):
        code,_=self.request('POST','/api/play',{'text':'我前往河街。','revision':0,'request_id':'approach-start'})
        self.assertEqual(code,200)
        before=self.engine.state()
        body={'text':'get close to anya','revision':before['revision'],'request_id':'approach-anya'}
        with patch('kobold_rpg.model._complete',side_effect=AssertionError('clear path needs no model')) as complete:
            code,result=self.request('POST','/api/play',body)
            retry_code,retry=self.request('POST','/api/play',body)
        self.assertEqual((code,retry_code),(200,200))
        self.assertEqual(result['status'],'routine')
        self.assertEqual(result['revision'],retry['revision'])
        self.assertEqual(self.engine.state()['pc']['location'],'pier')
        self.assertEqual(self.engine.state()['npcs']['anya'],before['npcs']['anya'])
        self.assertIn('安雅（Anya）',result['narration'])
        self.assertEqual(self.engine.history()[-1]['action']['text'],'get close to anya')
        complete.assert_not_called()
        self.assertTrue(self.engine.verify())

    def test_failed_audit_does_not_commit_a_sent_action(self):
        proposal={'outcome':'success','reason':'測試','narration':'無依據的結果。','events':[]}
        with patch('server.react',return_value=proposal),patch('server.audit_narration',side_effect=RuleError('核對未通過')):
            code,_=self.request('POST','/api/play',{'text':'我問哈克：「你好嗎？」','revision':0,'request_id':'fail'})
        self.assertEqual(code,400);self.assertEqual(self.engine.state()['revision'],0)

    def test_actual_pronoun_attack_reaches_referee_with_its_target(self):
        proposal={'outcome':'failure','reason':'哈克格擋了這次刺擊。','narration':'班刺出獵刀，哈克用短劍擋開刺向頸側的刀刃。','events':[]}
        audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['ben','hark'],'powers':[],'issues':[]}}
        with patch('server.react',return_value=proposal) as model,patch('server.audit_narration',return_value=audit):
            code,result=self.request('POST','/api/play',{'text':'aim for his neck and stab him','revision':0,'request_id':'pronoun-attack'})
        self.assertEqual(code,200);self.assertEqual(model.call_args.args[1]['target'],'hark')
        self.assertEqual(self.engine.history()[0]['narration'],proposal['narration'])
        self.assertEqual(self.engine.history()[0]['action']['target'],'hark')

    def test_question_with_kill_is_dialogue_and_never_calls_semantic_fallback(self):
        proposal={'outcome':'success','reason':'回應為何懷疑的問題。','narration':'哈克回答：「你剛才拿刀刺過來，我當然會戒備。」','events':[]}
        audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['ben','hark'],'powers':[],'issues':[]}}
        with patch('server.semantic_understanding',side_effect=AssertionError('clear question needs no extra call')),patch('server.react',return_value=proposal) as model,patch('server.audit_narration',return_value=audit):
            code,_=self.request('POST','/api/play',{'text':'why would i want to kill you','revision':0,'request_id':'question'})
        self.assertEqual(code,200);action=model.call_args.args[1]
        self.assertEqual(action['kind'],'speak');self.assertEqual(action['target'],'hark')
        self.assertEqual(action['understanding']['actions'],[])
        with patch('server.semantic_understanding',side_effect=AssertionError('retry must reuse interpretation')),patch('server.react',side_effect=AssertionError('retry must not generate')):
            code,_=self.request('POST','/api/play',{'text':'why would i want to kill you','revision':0,'request_id':'question'})
        self.assertEqual(code,200)

    def test_internal_missing_field_error_is_not_exposed_as_a_bare_key(self):
        with patch('server.react',side_effect=KeyError('type')):
            code,data=self.request('POST','/api/play',{'text':'我問哈克：「可以繼續嗎？」','revision':0,'request_id':'missing-type'})
        self.assertEqual(code,400);self.assertNotIn("'type'",data['error'])
        self.assertIn('資料不完整',data['error']);self.assertEqual(self.engine.state()['revision'],0)

    def test_repeated_dialogue_is_shown_and_committed_once_without_quality_retry(self):
        old='哈克（Hark）說：「若是為了找同伴，最好說明對方的特徵。別讓我覺得你是來搶我這最後一點補給的，或是想把我賣給那些怪物。」'
        previous={'outcome':'partial','reason':'回應找人的話。','narration':old,'events':[]}
        audit={'revision':0,'proposal_hash':digest(previous),'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
        first=self.engine.propose({'kind':'speak','target':'hark','text':'我在找人。'},previous,0,audit=audit)
        self.engine.approve(first['id'],'previous')
        proposal={'outcome':'partial','reason':'回應女人稀少的問題。',
                  'narration':'哈克（Hark）說：「我其實不知道鎮上有多少女人，那只是我的印象。」'+old,'events':[]}
        audit={'revision':1,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
        body={'text':'why are women so rare here','revision':1,'request_id':'show-repeated-reply'}
        with patch('server.semantic_understanding',side_effect=AssertionError('clear question needs no parser')),patch('kobold_rpg.model._complete',return_value=proposal) as model,patch('server.audit_narration',return_value=audit):
            code,result=self.request('POST','/api/play',body)
            self.assertEqual(code,200);self.assertEqual(result['status'],'approved')
            self.assertIn('只是我的印象',result['turn']['narration']);self.assertIn('最好說明對方的特徵',result['turn']['narration'])
            self.assertEqual(self.request('POST','/api/play',body)[0],200)
        self.assertEqual(model.call_count,1);self.assertEqual(self.engine.state()['revision'],2)
        self.assertEqual(self.engine.history()[-1]['action']['text'],body['text'])
        self.assertTrue(self.engine.verify())

    def test_unestablished_question_premise_is_clarified_by_the_npc(self):
        before=self.engine.state()
        proposal={'outcome':'partial','reason':'人物反問問題的前提。',
                  'narration':'哈克（Hark）問：「你指哪裡？我沒說過整個世界都是這樣。」','events':[]}
        audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
        with patch('kobold_rpg.model._complete',return_value=proposal) as model,patch('server.audit_narration',return_value=audit):
            code,result=self.request('POST','/api/play',{'text':'why are women so rare here','revision':0,'request_id':'npc-clarifies'})
        self.assertEqual(code,200);self.assertEqual(result['status'],'approved');self.assertIn('你指哪裡',result['turn']['narration'])
        self.assertEqual(model.call_count,1)
        self.assertEqual(self.engine.state()['canon'],before['canon']);self.assertEqual(self.engine.state()['locations'],before['locations'])

    def test_unspecified_addressee_in_a_group_is_asked_by_an_existing_npc(self):
        # Initial test fixture only: both established characters are present.
        state=self.engine.state();state['npcs']['anya']['location']=state['pc']['location']
        with self.engine.connect() as db:db.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),))
        proposal={'outcome':'partial','reason':'在場人物自然回問對象。','narration':'哈克（Hark）看了看安雅（Anya），問：「你是在問我，還是在問她？」','events':[]}
        audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['hark','anya'],'powers':[],'issues':[]}}
        with patch('kobold_rpg.model._complete',return_value=proposal) as model,patch('server.audit_narration',return_value=audit):
            code,result=self.request('POST','/api/play',{'text':'Why would you say that?','revision':0,'request_id':'group-question'})
        self.assertEqual(code,200);self.assertEqual(result['status'],'approved');self.assertIn('你是在問我',result['turn']['narration'])
        self.assertEqual(self.engine.history()[0]['action']['target'],'');self.assertEqual(model.call_count,1)

    def test_player_can_claim_an_unregistered_power_without_being_given_that_power(self):
        before=self.engine.state();text='我說：「我是會噴火的龍王。」'
        proposal={'outcome':'partial','reason':'人物質疑玩家的說法。','narration':'哈克（Hark）問：「你是認真的，還是在開玩笑？」','events':[]}
        audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
        with patch('kobold_rpg.model._complete',return_value=proposal),patch('server.audit_narration',return_value=audit):
            code,result=self.request('POST','/api/play',{'text':text,'revision':0,'request_id':'spoken-claim'})
        self.assertEqual(code,200);self.assertEqual(result['status'],'approved')
        after=self.engine.state();self.assertEqual(after['canon'],before['canon']);self.assertEqual(after['abilities'],before['abilities'])
        self.assertEqual(after['pc']['spells'],before['pc']['spells']);self.assertEqual(self.engine.history()[0]['action']['text'],text)

    def test_short_question_reaches_npc_without_semantic_call_and_keeps_original_punctuation(self):
        text='當交換條件?'
        proposal={'outcome':'partial','reason':'回應這句短反問。','narration':'哈克說：「你是在問我的意思嗎？」','events':[]}
        audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
        with patch('server.semantic_understanding',side_effect=AssertionError('no parser model needed')),patch('server.react',return_value=proposal) as model,patch('server.audit_narration',return_value=audit):
            code,_=self.request('POST','/api/play',{'text':text,'revision':0,'request_id':'short-question'})
        self.assertEqual(code,200)
        self.assertEqual(model.call_args.args[1]['understanding']['speech'],[text])
        self.assertEqual(self.engine.history()[0]['action']['text'],text)
        self.assertEqual(self.engine.history()[0]['action']['understanding']['speech'],[text])

    def test_fallback_punctuation_is_restored_but_actual_rewording_cannot_reach_npc(self):
        text='請再解釋，當交換條件?'
        parsed={'mode':'speech','actions':[],'speech':['請再解釋,當交換條件？'],'thoughts':[]}
        before=self.engine.state()
        with patch('server.semantic_understanding',return_value={**parsed,'speech':['請讓我當交換條件？']}),patch('server.react',side_effect=AssertionError('rewritten words must not reach narrator')):
            self.assertEqual(self.request('POST','/api/play',{'text':text,'revision':0,'request_id':'changed-words'})[0],400)
        self.assertEqual(self.engine.state(),before);self.assertEqual(self.engine.history(),[])
        proposal={'outcome':'partial','reason':'回應原句。','narration':'哈克說：「你想再確認剛才那句話的意思？」','events':[]}
        audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
        with patch('server.semantic_understanding',return_value=parsed),patch('server.react',return_value=proposal) as model,patch('server.audit_narration',return_value=audit):
            code,_=self.request('POST','/api/play',{'text':text,'revision':0,'request_id':'punctuation-only'})
        self.assertEqual(code,200);self.assertEqual(model.call_args.args[1]['understanding']['speech'],[text])
        self.assertEqual(self.engine.history()[0]['action']['text'],text)

    def test_request_progress_is_session_scoped_and_has_no_model_text(self):
        self.request('POST','/api/play',{'text':'環顧四周','revision':0,'request_id':'look'})
        code,job=self.request('GET','/api/progress?request_id=look')
        self.assertEqual(code,200);self.assertEqual(job['percent'],100);self.assertEqual(job['status'],'done')
        self.assertNotIn('narration',job)
        _,other=self.request('GET','/api/progress?request_id=look',session='another')
        self.assertEqual(other['status'],'waiting')
        self.assertEqual(self.request('GET','/api/progress?request_id=look',token='wrong')[0],404)

    def test_failed_world_draft_does_not_create_or_switch_world(self):
        with patch('server.generate_world',side_effect=RuleError('模型草案沒有通過核對。')):
            code,_=self.request('POST','/api/world/draft',{'preferences':fixture()['preferences']})
        self.assertEqual(code,400);self.assertEqual(self.library.previews,{})
        self.assertEqual(self.engine.state()['revision'],0)
        self.assertEqual(list((self.library.root/'campaigns').glob('*.sqlite3')),[])

    def test_local_library_requires_authorized_page(self):
        self.assertEqual(self.request('GET','/api/library',token='wrong')[0],404)
        self.assertEqual(self.request('POST','/api/save',{'name':'不應寫入'},token='wrong')[0],403)
        self.assertEqual(self.library.list()['saves'],[])

    def test_portable_download_and_import_restore_progress_with_new_session(self):
        self.engine.submit({'kind':'observe','text':'環顧四周'},'look',0)
        old_session=self.library.session_id
        code,data=self.request('GET','/api/save-file')
        self.assertEqual(code,200);self.assertEqual(data['format'],'kobold-rpg-save')
        self.assertEqual(self.request('GET','/api/save-file',token='wrong')[0],404)
        self.assertEqual(self.request('GET','/api/save-file',session='old')[0],400)
        code,_=self.request('POST','/api/import-file',{'save':data})
        self.assertEqual(code,200);self.assertNotEqual(self.library.session_id,old_session)
        self.assertEqual(self.library.engine.state(),self.engine.state())
        self.assertEqual(self.library.engine.history(),self.engine.history())

    def test_portable_import_accepts_large_valid_save_and_rejects_corruption(self):
        from kobold_rpg.portable import export_file
        for i in range(5):self.engine.submit({'kind':'observe','text':'再看一次'},str(i),i)
        data=export_file(self.engine)
        self.assertGreater(len(json.dumps({'save':data}).encode()),65536)
        self.assertEqual(self.request('POST','/api/import-file',{'save':data})[0],200)
        before=self.library.engine.state();nonce=self.library.session_id
        data['state']['pc']['name']='損壞'
        self.assertEqual(self.request('POST','/api/import-file',{'save':data})[0],400)
        self.assertEqual(self.library.engine.state(),before);self.assertEqual(self.library.session_id,nonce)

    def test_creation_options_explain_difficulty_and_derive_genre(self):
        code,data=self.request('GET','/api/creation-options')
        self.assertEqual(code,200)
        self.assertIn('困難',data['difficulties']);self.assertIn('日常小鎮',data['story_types'])

    def test_reading_current_story_remains_available_while_world_is_generated(self):
        started=threading.Event();release=threading.Event();results=[]
        def generating(*args):
            started.set();release.wait(4);return fixture()
        def post():
            results.append(self.request('POST','/api/world/draft',{'preferences':fixture()['preferences']}))
        with patch('server.generate_world',side_effect=generating):
            thread=threading.Thread(target=post);thread.start()
            try:
                self.assertTrue(started.wait(2))
                code,session=self.request('GET','/api/session')
                self.assertEqual(code,200)
                self.assertEqual(session['state']['revision'],0)
                self.assertFalse(release.is_set())
            finally:
                release.set();thread.join(5)
        self.assertEqual(results[0][0],200)


if __name__=='__main__':unittest.main()
