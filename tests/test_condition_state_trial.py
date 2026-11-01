import copy
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from kobold_rpg.calibrated_difficulty_trial import register_force_profile
from kobold_rpg.condition_state_trial import (apply_condition_result,
    make_condition_gm,narrate_condition,prepare_condition_decision)
from kobold_rpg.engine import Engine,RuleError
from test_dynamic_values_trial import object_fixture
from test_library import fixture as world_fixture
from test_structured_state_trial import action
from server import make_handler


class ConditionStateTrialTests(unittest.TestCase):
    def test_unpunctuated_question_follows_only_present_speaker(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'world.sqlite3',seed=world_fixture()['seed'])
            observations=[]
            gm=make_condition_gm(engine,observations=observations)
            with (patch('kobold_rpg.condition_state_trial.focused_dialogue',
                        return_value=('小禾說：「這裡是河邊的小店。」',120)) as dialogue,
                  patch('kobold_rpg.condition_state_trial.prepare_condition_decision',
                        side_effect=AssertionError('must not create a new NPC'))):
                reply=gm(engine.state(),'can you tell me more about this place','http://none')
            self.assertEqual(observations[-1]['route'],'focused_dialogue')
            self.assertEqual(dialogue.call_args.args[2],'guide')
            engine.record_gm_reply('can you tell me more about this place',reply,'solo-question',0)
            self.assertEqual(set(engine.state()['npcs']),{'guide'})
            self.assertTrue(engine.verify())

    def test_unnamed_question_with_two_present_people_requests_a_target(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'world.sqlite3',seed=world_fixture()['seed'])
            state=engine.state();other=copy.deepcopy(state['npcs']['guide'])
            other.update(id='neighbor',name='鄰居（Neighbor）')
            state['npcs']['neighbor']=other
            gm=make_condition_gm(engine)
            with self.assertRaisesRegex(RuleError,'請講明你想問邊位'):
                gm(state,'can you tell me more about this place','http://none')
            self.assertEqual(engine.state()['revision'],0)

    def test_injected_http_turn_commits_numeric_condition_once(self):
        seed=register_force_profile(object_fixture(),'side_door','reinforced',
            'breached',False,'厚木板和鐵箍','表面完整未有破口')
        text='我試著撞破側門。';calls=[]
        def complete(messages,*args,**kwargs):
            calls.append(messages)
            if '你是 RPG 敘述者' in messages[0]['content']:
                return {'narration':'你撞擊側門，門板出現破口，但仍然關著。'}
            return {'mode':'play','steps':[action('force','side_door',utterance=text)]}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            handler=make_handler(engine,'http://none','test',
                                 gm=make_condition_gm(engine,complete=complete))
            server=ThreadingHTTPServer(('127.0.0.1',0),handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                def send():
                    conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
                    try:
                        conn.request('POST','/api/play',json.dumps({'text':text,
                            'request_id':'condition-http-1','revision':0}),
                            {'Content-Type':'application/json','X-RPG-Token':'test'})
                        response=conn.getresponse()
                        return response.status,json.loads(response.read())
                    finally:conn.close()
                with patch('kobold_rpg.condition_state_trial._dice',
                           return_value=lambda sides:20):
                    code,first=send()
                self.assertEqual(code,200,first)
                before=len(calls)
                code,duplicate=send()
                self.assertEqual(code,200,duplicate)
                self.assertEqual(duplicate['revision'],first['revision'])
                self.assertEqual(len(calls),before)
                saved=engine.state()
                self.assertEqual(saved['revision'],1)
                self.assertEqual(saved['world']['entities']['side_door']['values']['integrity'],80)
                self.assertTrue(engine.verify())
            finally:
                server.shutdown();server.server_close();thread.join()
                handler.jobs.join();handler.illustrations.join()

    def test_first_contact_failure_then_repeat_success_updates_one_sourced_object(self):
        text='我試著撞破側門。'
        seed=object_fixture()
        def complete(messages,*args,**kwargs):
            if '按已有描述' in messages[0]['content']:
                return {'tier':'reinforced','effect_key':'breached','initial':False,
                        'source_quote':'厚木板和鐵箍',
                        'initial_source_quote':'表面完整未有破口'}
            return {'mode':'play','steps':[action('force','side_door',utterance=text)]}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            with patch('kobold_rpg.condition_state_trial._dice',
                       return_value=lambda sides:1):
                first=prepare_condition_decision(engine,'fail',0,text,'http://none',complete)
                duplicate=prepare_condition_decision(engine,'fail',0,text,'http://none',complete)
            self.assertEqual(first,duplicate)
            self.assertEqual(first['decision']['condition_delta'],
                             {'target_id':'side_door','before':100,'after':100,'damage':0})
            engine.record_gm_reply(text,{'narration':'撞擊未令門受損。',
                'changes':first['decision']['changes']},'fail',0)
            saved=engine.state();door=saved['world']['entities']['side_door']
            self.assertEqual(door['values']['integrity'],100)
            self.assertIs(door['values']['breached'],False)
            self.assertIn('表面完整',door['condition_sentence'])
            with patch('kobold_rpg.condition_state_trial._dice',
                       return_value=lambda sides:20):
                second=prepare_condition_decision(engine,'success',1,text,'http://none',complete)
            self.assertEqual(second['decision']['condition_delta']['after'],80)
            engine.record_gm_reply(text,{'narration':'門板出現破口。',
                'changes':second['decision']['changes']},'success',1)
            saved=engine.state();door=saved['world']['entities']['side_door']
            self.assertEqual(door['values']['integrity'],80)
            self.assertIs(door['values']['breached'],True)
            self.assertIs(door['values']['open'],False)
            self.assertIs(door['values']['locked'],True)
            with patch('kobold_rpg.condition_state_trial._dice',
                       return_value=lambda sides:20):
                third=prepare_condition_decision(engine,'repeat',2,text,'http://none',complete)
            self.assertEqual(third['decision']['condition_delta']['before'],80)
            self.assertEqual(third['decision']['condition_delta']['after'],60)
            self.assertTrue(engine.verify())

    def test_ai_narration_uses_condition_and_rejects_known_false_implications(self):
        state=register_force_profile(object_fixture(),'side_door','reinforced',
            'breached',False,'厚木板和鐵箍','表面完整未有破口')
        decision={'status':'resolved','steps':[{'action':'force','status':'succeeded',
                   'target_id':'side_door'}],
                  'rolls':[{'target_id':'side_door','total':20,'target':20,'success':True}],
                  'changes':{'world':{'entities':{'side_door':state['world']['entities']['side_door']}}}}
        decision=apply_condition_result(state,decision)
        captured=[]
        def valid(messages,*args,**kwargs):
            captured.append(messages)
            return {'narration':'你撞向側門，門板發出悶響並出現破口；門仍關著。'}
        text='我試著撞破側門。'
        prose,_=narrate_condition(state,text,decision,'http://none',valid)
        self.assertIn('出現破口',prose)
        self.assertIn('完整度 80/100',captured[0][0]['content'])
        for bad in ('側門破口已可容人通過。','側門已打開。',
                    '側門仍上鎖，但未完全開啟。','你用獵刀撞破側門。',
                    '側門完整度降到 40/100。','它出現破口。'):
            with self.subTest(bad=bad),self.assertRaises(RuleError):
                narrate_condition(state,text,decision,'http://none',
                                   lambda *args,**kwargs:{'narration':bad})

    def test_invalid_ai_story_falls_back_without_discarding_frozen_roll(self):
        seed=register_force_profile(object_fixture(),'side_door','reinforced',
            'breached',False,'厚木板和鐵箍','表面完整未有破口')
        text='我試著撞破側門。';calls=[];observations=[]
        def complete(messages,*args,**kwargs):
            calls.append(messages)
            if '你是 RPG 敘述者' in messages[0]['content']:
                return {'narration':'側門破口已可容人通過。'}
            return {'mode':'play','steps':[action('force','side_door',utterance=text)]}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            gm=make_condition_gm(engine,complete=complete,observations=observations)
            with patch('kobold_rpg.condition_state_trial._dice',
                       return_value=lambda sides:20):
                reply=gm(engine.state(),text,'http://none')
            self.assertEqual(observations[0]['narration_source'],'host_fallback')
            self.assertNotIn('可容人通過',reply['narration'])
            engine.record_gm_reply(text,reply,'fallback',0)
            self.assertEqual(engine.state()['world']['entities']['side_door']['values']['integrity'],80)
            self.assertTrue(engine.verify())
