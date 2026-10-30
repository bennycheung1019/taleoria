import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from kobold_rpg.engine import Engine,RuleError
from kobold_rpg.campaign import new_campaign
from kobold_rpg.library import CampaignLibrary
from kobold_rpg.canon import digest
from kobold_rpg.turn_updates import complete,latest,Runner
from kobold_rpg.model import react,enrich_characters
from kobold_rpg.portable import export_file
from server import make_handler

NARRATION='哈克說：「我得等到接班的人來。」'
NOTE={'type':'character_note','npc':'hark','kind':'said','quote':'我得等到接班的人來。'}
ACTION={'kind':'speak','target':'hark','text':'我問哈克：「現在可以聊一下嗎？」'}


def proposed():return {'outcome':'success','reason':'哈克回應。','narration':NARRATION,'events':[]}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.engine=Engine(Path(self.tmp.name)/'world.db',seed=new_campaign())

    def commit(self,events=None):
        proposal=proposed();proposal['events']=events or []
        audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
        pending=self.engine.propose(ACTION,proposal,0,audit=audit)
        return self.engine.approve(pending['id'],'play',defer_people=True)

    def test_ruling_is_available_before_metadata_and_metadata_only_applies_once(self):
        self.commit();self.assertEqual(self.engine.state()['revision'],1)
        self.assertEqual(latest(self.engine)['status'],'pending')
        self.assertNotIn('people_notes',self.engine.state())
        complete(self.engine,1,[NOTE]);before=self.engine.state()
        self.assertEqual(before['revision'],2);self.assertEqual(before['people_notes']['hark'][0]['quote'],NOTE['quote'])
        self.assertIsNone(latest(self.engine));self.assertTrue(self.engine.verify())
        complete(self.engine,1,[NOTE]);self.assertEqual(self.engine.state(),before)

    def test_background_cannot_move_characters_or_create_world_facts(self):
        self.commit();before=self.engine.state()
        for event in [{'type':'move','destination':'shelter'},{'type':'fact','text':'新增力量','visibility':'public'},
                      {**NOTE,'npc':'anya'},{**NOTE,'quote':'故事沒有說過的秘密。'}]:
            with self.assertRaises(RuleError):complete(self.engine,1,[event])
            self.assertEqual(self.engine.state(),before)

    def test_source_encounter_survives_npc_departure_without_teleporting_anyone(self):
        self.commit([{'type':'npc_move','npc':'hark','from':'gate','destination':'shelter','basis':'有可信交接安排後到旁邊避雨。'}])
        complete(self.engine,1,[NOTE])
        state=self.engine.state();self.assertEqual(state['npcs']['hark']['location'],'shelter')
        self.assertEqual(state['pc']['location'],'gate');self.assertEqual(state['people_notes']['hark'][0]['quote'],NOTE['quote'])

    def test_stale_background_result_is_rejected(self):
        self.commit();self.engine.submit({'kind':'observe','text':'環顧四周'},'external-change',1)
        before=self.engine.state()
        with self.assertRaises(RuleError):complete(self.engine,1,[NOTE])
        self.assertEqual(self.engine.state(),before)

    def test_emotional_memory_is_private_and_does_not_move_a_departed_character(self):
        self.commit([{'type':'npc_move','npc':'hark','from':'gate','destination':'shelter','basis':'有可信交接安排後到旁邊避雨。'}])
        event={'type':'social_experience','npc':'hark','subject':'ben','observed':'聽到班詢問能否交談。',
               'interpretation':'仍有職責，願意保持簡短交談。','emotions':['願意交談，但仍顧及交班'],'changes':{},'recalls':[]}
        complete(self.engine,1,[event]);state=self.engine.state()
        self.assertEqual(state['npcs']['hark']['location'],'shelter')
        self.assertEqual(len(state['npcs']['hark']['inner_life']['memories']),1)
        self.assertEqual(state['npcs']['hark']['inner_life']['current_emotions'][0]['feeling'],event['emotions'][0])
        self.assertNotIn('inner_life',json.dumps(self.engine.public_state()))

    def test_complete_file_waits_for_metadata_and_contains_accepted_update_afterwards(self):
        self.commit()
        with self.assertRaises(RuleError):export_file(self.engine)
        complete(self.engine,1,[NOTE]);payload=export_file(self.engine)
        self.assertEqual(payload['state']['revision'],2)
        restored=CampaignLibrary(Path(self.tmp.name)/'library',self.engine)
        restored.import_file(payload)
        self.assertEqual(restored.engine.state(),self.engine.state());self.assertIsNone(latest(restored.engine))

    def test_pending_job_survives_process_restart(self):
        self.commit();restored=Engine(self.engine.path);calls=[]
        runner=Runner(threading.RLock(),'http://local',lambda *args:calls.append(args) or [NOTE])
        runner.kick(restored);runner.join()
        self.assertEqual(len(calls),1);self.assertIsNone(latest(restored));self.assertEqual(restored.state()['revision'],2)
        runner.kick(restored);runner.join();self.assertEqual(len(calls),1)

    def test_player_reply_has_no_second_voice_generation_or_future_answers(self):
        with patch('kobold_rpg.model._complete',return_value=proposed()) as model:
            result=react(self.engine.state(),ACTION,'http://local',recent=['前一段已接受故事。'])
        self.assertEqual(model.call_count,1);self.assertEqual(result['narration'],NARRATION)
        request=model.call_args.args[0]
        self.assertIn('不預寫選項',request[0]['content']);self.assertNotIn('social_experience 保留',request[0]['content'])
        # Verified source quotations now share the single system message;
        # the compact narrator instructions remain independently bounded.
        instructions=request[0]['content'].split('已核對的 RPG OS 原規則摘錄：',1)[0]
        self.assertLess(len(instructions),1600)

    def test_simple_information_question_indexes_quote_without_another_model_call(self):
        action={**ACTION,'text':'我問哈克：「今晚還會下雨嗎？」'}
        narration='哈克（Hark）看了看天空，回答道：『應該還會下一陣雨。』'
        with patch('kobold_rpg.model._complete',side_effect=AssertionError('ordinary question needs no reflection')):
            events=enrich_characters(self.engine.state(),action,narration,'http://local')
        self.assertEqual(events,[{'type':'character_note','npc':'hark','kind':'said','quote':'應該還會下一陣雨。'}])

    def test_player_quote_is_not_misattributed_as_an_npc_statement(self):
        with patch('kobold_rpg.model._complete',side_effect=AssertionError('no extra call')):
            events=enrich_characters(self.engine.state(),{**ACTION,'text':'我問今晚是否下雨。'},'你問：「今晚還會下雨嗎？」哈克看向天際。','http://local')
        self.assertEqual(events,[])

    def test_reflection_binds_old_values_to_locked_state_and_merges_one_experience(self):
        state=self.engine.state();before=copy.deepcopy(state)
        action={**ACTION,'text':'我謝謝哈克的體諒。'}
        first={'type':'social_experience','npc':'hark','subject':'ben','observed':'班表達感謝。',
               'interpretation':'感到自己的工作受到體諒。','emotions':['感激'],'changes':{'respect':{'before':'模型抄錯的舊值','after':'欣賞對方的體諒'}},'recalls':[]}
        second={**copy.deepcopy(first),'emotions':['輕鬆了一點'],'changes':{'respect':'欣賞對方的體諒','trust':None}}
        with patch('kobold_rpg.model._complete',return_value={'events':[first,second]}):
            result=enrich_characters(state,action,NARRATION,'http://local')
        social=[e for e in result if e['type']=='social_experience']
        self.assertEqual(len(social),1);self.assertEqual(social[0]['changes'],{'respect':{'before':None,'after':'欣賞對方的體諒'}})
        self.assertEqual(social[0]['emotions'],['感激','輕鬆了一點']);self.assertEqual(state,before)

    def test_conflicting_reflections_do_not_overwrite_each_other(self):
        event={'type':'social_experience','npc':'hark','subject':'ben','observed':'班表達感謝。',
               'interpretation':'體諒工作。','emotions':['感激'],'changes':{'respect':'一個新狀態'},'recalls':[]}
        other={**copy.deepcopy(event),'changes':{'respect':'另一個矛盾狀態'}}
        with patch('kobold_rpg.model._complete',return_value={'events':[event,other]}):
            with self.assertRaises(RuleError):enrich_characters(self.engine.state(),{**ACTION,'text':'我謝謝哈克。'},NARRATION,'http://local')


class StoryFirstHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.engine=Engine(Path(self.tmp.name)/'world.db',seed=new_campaign());self.library=CampaignLibrary(Path(self.tmp.name)/'library',self.engine)
        self.started=threading.Event();self.release=threading.Event();self.should_fail=False;self.calls=0
        def enrich(*args):
            self.calls+=1;self.started.set();self.release.wait(4)
            if self.should_fail:raise RuleError('不應傳給玩家的私人錯誤')
            return [NOTE]
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.engine,'http://local','token',self.library,enricher=enrich,planner=None,gm=None))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.stop)

    def stop(self):
        self.release.set();self.server.shutdown();self.server.server_close();self.thread.join();self.server.RequestHandlerClass.background.join()

    def request(self,method,path,body=None,session=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=2)
        try:
            if body is not None:body={**body,'session_id':session or self.library.session_id}
            conn.request(method,path,body=json.dumps(body) if body is not None else None,
                headers={'Content-Type':'application/json','X-RPG-Token':'token','X-RPG-Session':session or self.library.session_id})
            response=conn.getresponse();return response.status,json.loads(response.read())
        finally:conn.close()

    def play(self):
        audit={'revision':0,'proposal_hash':digest(proposed()),'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
        with patch('server.react',return_value=proposed()),patch('server.audit_narration',return_value=audit):
            return self.request('POST','/api/play',{'text':ACTION['text'],'revision':0,'request_id':'play'})

    def test_story_returns_with_current_public_panels_while_background_waits(self):
        code,result=self.play();self.assertEqual(code,200);self.assertIn('我得等到',result['turn']['narration'])
        self.assertTrue(self.started.wait(1));self.assertFalse(self.release.is_set())
        snapshot=result['panel_snapshot']
        self.assertEqual(snapshot['revision'],1)
        self.assertEqual(snapshot['pc']['inventory'],self.engine.public_state()['pc']['inventory'])
        self.assertNotIn('inner_life',json.dumps(snapshot,ensure_ascii=False))
        _,panels=self.request('GET','/api/panels')
        self.assertIsNone(panels['state']);self.assertEqual(panels['views']['status'],'pending')
        self.assertEqual(panels['panel_snapshot'],snapshot)
        _,session=self.request('GET','/api/session');self.assertIsNone(session['state']);self.assertEqual(len(session['history']),1)
        self.assertEqual(self.request('GET','/api/save-file')[0],400)
        self.assertEqual(self.request('GET','/api/panels',session='stale')[0],400)
        self.release.set();self.server.RequestHandlerClass.background.join()
        _,ready=self.request('GET','/api/panels')
        self.assertEqual(ready['state']['revision'],2);self.assertEqual(ready['views']['status'],'ready')
        self.assertEqual(len(ready['history']),1);self.assertEqual(self.calls,1)
        self.assertIn(NOTE['quote'],[v['quote'] for v in ready['state']['people']['hark']['facts']])
        with patch('server.react',side_effect=AssertionError('do not replay story')):
            code,_=self.request('POST','/api/play',{'text':ACTION['text'],'revision':0,'request_id':'play'})
        self.assertEqual(code,200);self.assertEqual(self.engine.state()['revision'],2)

    def test_failed_metadata_keeps_story_and_retry_does_not_replay_action(self):
        self.should_fail=True;self.release.set();self.play();self.assertTrue(self.started.wait(1));self.server.RequestHandlerClass.background.join()
        _,data=self.request('GET','/api/panels')
        self.assertIsNone(data['state']);self.assertEqual(data['views']['status'],'error')
        self.assertEqual(data['panel_snapshot']['revision'],1)
        self.assertIn('pc',data['panel_snapshot']);self.assertIn('atlas',data['panel_snapshot'])
        self.assertEqual(len(data['history']),1);self.assertNotIn('私人錯誤',json.dumps(data,ensure_ascii=False))
        self.assertEqual(self.engine.state()['revision'],1)
        self.should_fail=False
        with patch('server.react',side_effect=AssertionError('do not replay story')):
            self.assertEqual(self.request('POST','/api/updates/retry',{})[0],200)
            self.server.RequestHandlerClass.background.join()
        self.assertEqual(self.calls,2);self.assertEqual(self.engine.state()['revision'],2)
        _,history=self.request('GET','/api/history');self.assertEqual(len(history),1)


if __name__=='__main__':unittest.main()
