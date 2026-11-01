import copy
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from kobold_rpg.calibrated_difficulty_trial import (compile_calibrated_action,
                                                    register_force_profile)
from kobold_rpg.calibrated_gm_trial import focused_dialogue,make_calibrated_gm
from kobold_rpg.engine import Engine
from kobold_rpg.engine import RuleError
from kobold_rpg.worldgen import build_world,generate_world
from server import make_handler
from test_dynamic_values_trial import object_fixture
from test_library import fixture as world_fixture
from test_structured_state_trial import action


class CalibratedHTTPTrialTests(unittest.TestCase):
    def test_new_world_scene_objects_are_sourced_capped_and_profiled_in_one_plan(self):
        candidate=world_fixture();plan=copy.deepcopy(candidate['plan'])
        quote='側門由厚木板和鐵箍做成，表面完整未有破口。'
        plan['location']['description']=quote+'店主正在整理藥草。'
        item={'name':'側門','type':'door','source_quote':quote,
              'force_profile':{'tier':'reinforced','effect_key':'breached',
                  'initial':False,'source_quote':'厚木板和鐵箍',
                  'initial_source_quote':'表面完整未有破口'}}
        plan['location']['objects']=[item]
        state=build_world(plan,candidate['preferences'])
        door=state['world']['entities']['scene_object_1']
        self.assertEqual(door['force_profile']['tier'],'reinforced')
        self.assertIs(door['values']['breached'],False)
        self.assertEqual(door['description'],quote)
        bad=copy.deepcopy(plan);bad['location']['objects'][0]['source_quote']='玩家聲稱另有金門'
        with self.assertRaises(RuleError):build_world(bad,candidate['preferences'])
        bad=copy.deepcopy(plan);bad['location']['objects']=[item]*21
        with self.assertRaises(RuleError):build_world(bad,candidate['preferences'])

    def test_staging_world_generation_extracts_sourced_objects_in_one_extra_call(self):
        candidate=world_fixture();description=candidate['plan']['location']['description']
        with (patch('kobold_rpg.worldgen._complete',return_value=candidate['plan']) as draft,
              patch('kobold_rpg.scene_setup_trial._complete',return_value={
                  'objects':[{'name_quote':'木門','type':'door',
                              'source_quote':'木門旁有一張長凳'}]}) as extractor):
            result=generate_world(candidate['preferences'],'http://none',scene_trial=True)
        self.assertEqual(draft.call_count,1)
        self.assertEqual(extractor.call_count,1)
        self.assertEqual(result['scene_setup']['accepted'],1)
        self.assertEqual(result['seed']['world']['entities']['scene_object_1']['name'],'木門')
        self.assertEqual(result['seed']['locations']['start']['description'],description)

    def test_scene_extraction_rejects_people_and_distant_objects(self):
        from kobold_rpg.scene_setup_trial import extract_scene_objects
        description=('僅有一扇側門可供通行，門前站著一名守衛。'
                     '遠處可見幾間低矮木屋與拴馬樁。')
        raw={'objects':[
            {'name_quote':'側門','type':'door','source_quote':'僅有一扇側門可供通行'},
            {'name_quote':'守衛','type':'object','source_quote':'門前站著一名守衛'},
            {'name_quote':'木屋','type':'object','source_quote':'遠處可見幾間低矮木屋'},
            {'name_quote':'拴馬樁','type':'object','source_quote':'拴馬樁'}]}
        rows,rejected,_=extract_scene_objects(description,'http://none',
                                               complete=lambda *args,**kwargs:raw)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(rejected),3)
        self.assertEqual(rows[0]['name'],'側門')
        self.assertEqual(rows[0]['source_quote'],description.split('。')[0]+'。')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        seed=register_force_profile(object_fixture(),'side_door','reinforced','breached',False,
                                    '厚木板和鐵箍','表面完整未有破口')
        self.engine=Engine(Path(self.tmp.name)/'copy.sqlite3',seed=seed)
        self.calls=[];self.observations=[];self.legacy_recent=[]
        def fake_complete(messages,*args,**kwargs):
            self.calls.append(messages)
            text=messages[-1]['content'] if len(messages)>1 else ''
            if '只回 JSON narration' in messages[0]['content']:
                return {'narration':'哈克說：「我聽見撞擊聲，但沒有看見門後面。」'}
            if '撞破側門' in text and 'decision_id' not in messages[0]['content']:
                return {'mode':'play','steps':[action('force','side_door',utterance=text)]}
            if '側門的變化' in text:
                return {'mode':'play','steps':[action('unknown','hark',utterance=text)]}
            if '推開側門' in text:
                return {'mode':'play','steps':[action('open','side_door',utterance=text)]}
            if '詢問守衛' in text:
                return {'mode':'play','steps':[action('custom','hark',utterance=text)]}
            return {'decision_id':'invalid','narration':'不能接受的模型敘述'}
        def legacy(state,text,base_url,recent=None,state_provenance=None):
            self.legacy_recent.append(recent)
            return {'narration':'哈克聽完你的問題，仍站在側門旁。','changes':{}}
        gm=make_calibrated_gm(self.engine,legacy_gm=legacy,
                              complete=fake_complete,observations=self.observations)
        self.handler=make_handler(self.engine,'http://none','test',gm=gm)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),self.handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start();self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.handler.jobs.join();self.handler.illustrations.join()

    def send(self,text,request_id,revision):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        try:
            conn.request('POST','/api/play',json.dumps({'text':text,'request_id':request_id,
                'revision':revision}),{'Content-Type':'application/json','X-RPG-Token':'test'})
            response=conn.getresponse()
            return response.status,json.loads(response.read())
        finally:conn.close()

    def test_force_duplicate_then_npc_turn_preserves_recent_story_and_save(self):
        with patch('kobold_rpg.calibrated_pending_trial._dice',
                   return_value=lambda sides:20):
            code,first=self.send('我試著撞破側門。','force-1',0)
        self.assertEqual(code,200,first)
        self.assertIn('破口',first['narration'])
        self.assertEqual(self.observations[0]['narration_source'],'host')
        self.assertEqual(len(self.calls),1)
        self.assertNotIn('獵刀',first['narration'])
        self.assertNotIn('門已打開',first['narration'])
        after=self.engine.state()
        self.assertEqual(after['revision'],1)
        self.assertIs(after['world']['entities']['side_door']['values']['breached'],True)
        self.assertIs(after['world']['entities']['side_door']['values']['open'],False)
        before_calls=len(self.calls)
        code,again=self.send('我試著撞破側門。','force-1',0)
        self.assertEqual(code,200,again)
        self.assertEqual(again['revision'],first['revision'])
        self.assertEqual(len(self.calls),before_calls)
        code,second=self.send('我詢問守衛發生甚麼事。','talk-2',1)
        self.assertEqual(code,200,second)
        self.assertEqual(self.engine.state()['revision'],2)
        self.assertEqual(self.observations[-1]['route'],'legacy')
        self.assertTrue(self.legacy_recent)
        self.assertIn('破口',str(self.legacy_recent[-1]))
        self.assertTrue(self.engine.verify())

    def test_focused_npc_question_uses_recent_event_without_changing_door(self):
        with patch('kobold_rpg.calibrated_pending_trial._dice',
                   return_value=lambda sides:20):
            code,_=self.send('我試著撞破側門。','force-q',0)
        self.assertEqual(code,200)
        text='我詢問守衛：「你見到側門的變化嗎？」'
        code,reply=self.send(text,'question-q',1)
        self.assertEqual(code,200,reply)
        self.assertEqual(self.observations[-1]['route'],'focused_dialogue')
        self.assertIn('沒有看見門後面',reply['narration'])
        self.assertIs(self.engine.state()['world']['entities']['side_door']['values']['breached'],True)
        self.assertEqual(self.engine.state()['revision'],2)
        self.assertTrue(self.engine.verify())

    def test_break_verb_normalizes_custom_but_negation_and_unwired_mechanics_do_not_commit(self):
        state=self.engine.state()
        state['world']['entities']['crate']={
            'name':'木箱','type':'crate','location':'gate',
            'description':'木箱由薄木板釘成，外表完整未有破損。',
            'values':{},'value_sources':{}}
        text='我試著敲破木箱。'
        proposal={'mode':'play','steps':[action('custom','crate',utterance=text)]}
        compiled,_=compile_calibrated_action(state,text,'http://none',
                                             lambda *args,**kwargs:proposal)
        self.assertEqual(compiled['steps'][0]['action'],'force')
        negated={'mode':'play','steps':[action('custom','crate',utterance='我不敲破木箱。',
                                             negated=True)]}
        compiled,_=compile_calibrated_action(state,'我不敲破木箱。','http://none',
                                             lambda *args,**kwargs:negated)
        self.assertEqual(compiled['steps'][0]['action'],'custom')
        code,response=self.send('我推開側門','not-wired',0)
        self.assertEqual(code,400,response)
        self.assertEqual(self.engine.state()['revision'],0)
        self.assertTrue(self.engine.verify())

    def test_pronoun_dialogue_loads_latest_changed_object_state(self):
        state=self.engine.state();door=state['world']['entities']['side_door']
        door['values']['breached']=True
        door['value_sources']['breached']={'revision':1,'source':'successful force roll'}
        state['revision']=1
        recent=[{'revision':1,'declaration':'我撞破側門','narration':'側門出現破口，但仍關著。',
                 'witnesses':['hark']}]
        captured=[]
        def complete(messages,*args,**kwargs):
            captured.append(messages)
            return {'narration':'哈克望向側門：「佢而家有破口，但仍關著。」'}
        prose,_=focused_dialogue(state,'我問哈克：「咁佢而家點？」','hark',recent,
                                 'http://none',complete)
        self.assertIn('有破口',prose)
        self.assertIn('側門目前已有破口',captured[0][0]['content'])
        self.assertIn('側門目前仍然關著',captured[0][0]['content'])
        self.assertIn('咁側門而家點',captured[0][0]['content'])
