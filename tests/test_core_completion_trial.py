import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kobold_rpg.calibrated_difficulty_trial import register_force_profile,resolve_force
from kobold_rpg.condition_state_trial import (make_condition_gm,apply_condition_result,
    reconcile_narrative_amendments)
from kobold_rpg.engine import Engine,RuleError
from kobold_rpg.gm_context import recent_context,recalled_object_context
from kobold_rpg.structured_state_trial import resolve_values,render_host_narration
from test_dynamic_values_trial import object_fixture
from test_structured_state_trial import action
from test_social_values_trial import fixture as social_fixture


class CoreCompletionTrialTests(unittest.TestCase):
    def test_narrated_extra_fact_is_committed_atomically_when_supported(self):
        seed=object_fixture()
        seed['world']['entities']['crate']={
            'name':'木箱','type':'crate','location':'gate',
            'description':'木箱由薄木板釘成，外表完整未有破損。',
            'values':{},'value_sources':{}}
        seed=register_force_profile(seed,'crate','light','broken',False,
                                    '薄木板釘成','外表完整未有破損')
        intent={'mode':'play','steps':[action('force','crate',
            utterance='我試著敲破木箱。')]}
        decision=apply_condition_result(seed,resolve_force(seed,intent,
                                            roller=lambda sides:20))
        prose='木箱箱板碎裂，箱蓋翻開；箱內空無一物。'
        additions=[{'field':'lid_open','value':True,'evidence':'箱蓋翻開'},
                   {'field':'contents','value':'empty','evidence':'箱內空無一物'}]
        revised=reconcile_narrative_amendments(seed,decision,prose,additions)
        box=revised['changes']['world']['entities']['crate']
        self.assertIs(box['values']['lid_open'],True)
        self.assertEqual(box['values']['contents'],'empty')
        self.assertNotIn('箱內情況',box['condition_unknowns'])
        with self.assertRaises(RuleError):reconcile_narrative_amendments(
            seed,decision,'木箱箱體明顯受損。',
            [{'field':'lid_open','value':True,'evidence':'木箱箱體明顯受損'}])
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            engine.record_gm_reply('我試著敲破木箱。',
                {'narration':prose,'changes':revised['changes']},'narrative-truth',0)
            saved=engine.state()['world']['entities']['crate']
            self.assertEqual(saved['values']['contents'],'empty')
            self.assertIn('箱內空無一物',saved['value_sources']['contents']['source'])
            self.assertTrue(engine.verify())

    def test_gm_commits_compatible_narrated_fact_in_same_turn(self):
        seed=object_fixture();text='我試著敲破木箱。';observations=[]
        seed['world']['entities']['crate']={
            'name':'木箱','type':'crate','location':'gate',
            'description':'木箱由薄木板釘成，外表完整未有破損。',
            'values':{},'value_sources':{}}
        seed=register_force_profile(seed,'crate','light','broken',False,
                                    '薄木板釘成','外表完整未有破損')
        def complete(messages,*args,**kwargs):
            if '你是 RPG 敘述者' in messages[0]['content']:
                return {'narration':'木箱碎裂，箱蓋翻開；箱內空無一物。',
                        'amendments':[
                            {'field':'lid_open','value':True,'evidence':'箱蓋翻開'},
                            {'field':'contents','value':'empty','evidence':'箱內空無一物'}]}
            return {'mode':'play','steps':[action('force','crate',utterance=text)]}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            gm=make_condition_gm(engine,complete=complete,observations=observations)
            with patch('kobold_rpg.condition_state_trial._dice',
                       return_value=lambda sides:20):
                reply=gm(engine.state(),text,'http://none')
            self.assertEqual(observations[-1]['narration_source'],'ai')
            self.assertEqual(len(observations[-1]['narrative_amendments']),2)
            engine.record_gm_reply(text,reply,'integrated-amendment',0)
            box=engine.state()['world']['entities']['crate']
            self.assertEqual(box['values']['contents'],'empty')
            self.assertIs(box['values']['lid_open'],True)
            after_observations=[]
            gm=make_condition_gm(engine,complete=lambda *args,**kwargs:
                {'narration':'哈克說：「箱內空無一物。」'},
                observations=after_observations)
            response=gm(engine.state(),'我問哈克：「木箱裡面有甚麼？」','http://none')
            self.assertEqual(after_observations[-1]['route'],'focused_dialogue')
            self.assertIn('空無一物',response['narration'])

    def test_narration_cannot_promote_small_locked_breach_to_passage(self):
        seed=register_force_profile(object_fixture(),'side_door','reinforced',
            'breached',False,'厚木板和鐵箍','表面完整未有破口')
        decision=apply_condition_result(seed,resolve_force(seed,{'mode':'play',
            'steps':[action('force','side_door',utterance='我撞破側門')]},
            roller=lambda sides:20))
        with self.assertRaises(RuleError):reconcile_narrative_amendments(
            seed,decision,'側門破口足以讓人通過。',
            [{'field':'passable','value':True,'evidence':'足以讓人通過'}])
        with self.assertRaises(RuleError):reconcile_narrative_amendments(
            seed,decision,'側門已打開。',
            [{'field':'open','value':True,'evidence':'側門已打開'}])
        self.assertNotIn('passable',seed['world']['entities']['side_door']['values'])

    def test_social_request_respects_knowledge_gate_and_durable_permission(self):
        text='我請哈克讓我進城。'
        def complete(messages,*args,**kwargs):
            if '只識別這次請求對應' in messages[0]['content']:
                return {'contract_id':'gate_entry','selected_factor_ids':[]}
            return {'mode':'play','steps':[action('persuade','hark',utterance=text)]}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'blocked.sqlite3',seed=social_fixture())
            gm=make_condition_gm(engine,complete=complete)
            with patch('kobold_rpg.condition_state_trial._dice',
                       return_value=lambda sides:20):
                reply=gm(engine.state(),text,'http://none')
            self.assertIn('未見到有效通行證',reply['narration'])
            engine.record_gm_reply(text,reply,'blocked',0)
            self.assertNotIn('permissions',engine.state()['world'])
            self.assertEqual(engine.state()['world']['social_outcomes']['revision_1']['status'],
                             'blocked')
            self.assertTrue(engine.verify())
            seeded=social_fixture()
            seeded['npcs']['hark']['social_state']['knowledge']['player_has_pass']={
                'known':True,'text':'班已出示有效通行證。',
                'revision':0,'source':'verified pass at setup'}
            approved=Engine(Path(folder)/'approved.sqlite3',seed=seeded)
            gm=make_condition_gm(approved,complete=complete)
            with patch('kobold_rpg.condition_state_trial._dice',
                       return_value=lambda sides:20):
                granted=gm(approved.state(),text,'http://none')
            self.assertIn('可以進城',granted['narration'])
            approved.record_gm_reply(text,granted,'granted',0)
            self.assertTrue(approved.state()['world']['permissions']['gate_entry']['granted'])
            self.assertEqual(approved.state()['world']['social_outcomes']['revision_1']['status'],
                             'succeeded')
            self.assertTrue(approved.verify())

    def test_information_question_cannot_bypass_social_knowledge_gate(self):
        seed=social_fixture()
        seed['npcs']['hark']['social_state']['knowledge']['shift_time']={
            'known':False,'text':'','revision':0,'source':'schedule not established'}
        text='我問哈克：「幾時交班？」'
        def complete(messages,*args,**kwargs):
            if '只識別這次請求對應' in messages[0]['content']:
                return {'contract_id':'shift_question','selected_factor_ids':[]}
            return {'mode':'play','steps':[action('persuade','hark',utterance=text)]}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            gm=make_condition_gm(engine,complete=complete)
            reply=gm(engine.state(),text,'http://none')
            self.assertIn('沒有可靠的交班時間',reply['narration'])
            self.assertNotIn('天亮後',reply['narration'])
            engine.record_gm_reply(text,reply,'shift-unknown',0)
            self.assertEqual(engine.state()['world']['social_outcomes']['revision_1']['status'],
                             'blocked')

    def test_observation_uses_established_description_and_respects_location(self):
        seed=object_fixture()
        shown=resolve_values(seed,{'mode':'play','steps':[
            action('observe','side_door',utterance='我查看側門。')]})
        narration=render_host_narration(seed,shown)
        self.assertIn('厚木板和鐵箍',narration)
        self.assertEqual(shown['status'],'resolved')
        distant=copy.deepcopy(seed);distant['pc']['location']='pier'
        denied=resolve_values(distant,{'mode':'play','steps':[
            action('observe','side_door',utterance='我查看側門。')]})
        self.assertEqual(denied['status'],'needs_judgment')
        self.assertEqual(denied['changes'],{})

    def test_distant_npc_does_not_inherit_remote_object_secret(self):
        seed=object_fixture();seed['pc']['location']='pier'
        text='我問安雅：「北門側門後面藏著甚麼？」'
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            gm=make_condition_gm(engine,complete=lambda *args,**kwargs:
                self.fail('A remote unknown must not be sent to the model as NPC knowledge'))
            reply=gm(engine.state(),text,'http://none')
            self.assertIn('唔清楚',reply['narration'])
            self.assertEqual(reply['changes'],{'scene_focus':['anya']})
            self.assertEqual(engine.state()['revision'],0)

    def test_material_tier_changes_damage_but_not_unknown_contents(self):
        seed=object_fixture()
        seed['world']['entities']['crate']={
            'name':'木箱','type':'crate','location':'gate',
            'description':'木箱由薄木板釘成，外表完整未有破損。',
            'values':{},'value_sources':{}}
        seed=register_force_profile(seed,'crate','light','broken',False,
                                    '薄木板釘成','外表完整未有破損')
        intent={'mode':'play','steps':[action('force','crate',
                 utterance='我試著敲破木箱。')]}
        decision=apply_condition_result(seed,resolve_force(seed,intent,
                                           roller=lambda sides:20))
        self.assertEqual(decision['condition_delta']['damage'],50)
        crate=decision['changes']['world']['entities']['crate']
        self.assertEqual(crate['values']['integrity'],50)
        self.assertIn('箱內情況',crate['condition_sentence'])
        self.assertNotIn('contents',crate['values'])

    def test_old_object_change_is_recalled_without_other_locations_or_false_knowers(self):
        seed=register_force_profile(object_fixture(),'side_door','reinforced',
            'breached',False,'厚木板和鐵箍','表面完整未有破口')
        other=copy.deepcopy(seed['world']['entities']['side_door'])
        other['location']='shelter';other['name']='側門'
        seed['world']['entities']['shelter_door']=other
        text='我試著撞破側門。'
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            decision=resolve_force(seed,{'mode':'play','steps':[
                action('force','side_door',utterance=text)]},roller=lambda sides:20)
            decision=apply_condition_result(seed,decision)
            engine.record_gm_reply(text,{'narration':'側門出現破口，仍關著。',
                'changes':decision['changes']},'old-force',0)
            for revision in range(1,6):
                engine.record_gm_reply('我等一陣。',{'narration':'你等了一陣。',
                    'changes':{}},'wait-'+str(revision),revision)
            saved=engine.state();recent,_=recent_context(engine,saved)
            self.assertNotIn(1,[row['revision'] for row in recent])
            older=recalled_object_context(engine,saved,'側門點樣？',
                [row['revision'] for row in recent])
            self.assertEqual(len(older),1)
            self.assertEqual(older[0]['revision'],1)
            self.assertEqual(older[0]['after_values']['integrity'],80)
            self.assertEqual(older[0]['current_values']['integrity'],80)
            self.assertIn('hark',older[0]['people_present_not_proven_knowers'])
            captured=[];observations=[]
            def dialogue(messages,*args,**kwargs):
                captured.append(messages)
                return {'narration':'哈克說：「側門現在有破口，但仍關著；我不知道門後面。」'}
            gm=make_condition_gm(engine,complete=dialogue,observations=observations)
            spoken=gm(saved,'我問哈克：「側門現在怎樣？」','http://none')
            self.assertIn('仍關著',spoken['narration'])
            self.assertEqual(observations[-1]['older_object_events'],1)
            self.assertIn('people_present_not_proven_knowers',captured[0][0]['content'])
            self.assertIn('"integrity":80',captured[0][0]['content'])
            pronoun=gm(saved,'我問哈克：「佢而家點？」','http://none')
            self.assertIn('仍關著',pronoun['narration'])
            self.assertEqual(observations[-1]['older_object_events'],1)
            self.assertIn('側門而家點',captured[-1][0]['content'])
            before_calls=len(captured)
            guarded=gm(saved,'我問哈克：「側門後面有甚麼？」','http://none')
            self.assertIn('我唔清楚',guarded['narration'])
            self.assertEqual(observations[-1]['route'],'knowledge_guard')
            self.assertEqual(len(captured),before_calls)
            elsewhere=engine.state();elsewhere['pc']['location']='shelter'
            self.assertEqual(recalled_object_context(engine,elsewhere,'側門點樣？'),[])
            self.assertTrue(engine.verify())

    def test_force_unlock_open_move_keep_distinct_state_and_chronology(self):
        seed=register_force_profile(object_fixture(),'side_door','reinforced',
            'breached',False,'厚木板和鐵箍','表面完整未有破口')
        texts=[('我試著撞破側門。','force','side_door',None),
               ('我用開鎖工具試著解開側門的鎖。','unlock','side_door','lockpick'),
               ('我推開側門。','open','side_door',None),
               ('我走到城門旁的避雨棚。','move','shelter',None)]
        def complete(messages,*args,**kwargs):
            text=messages[-1]['content']
            if '你是 RPG 敘述者' in messages[0]['content']:
                return {'narration':'你撞向側門，門板有了破口，門仍關著。'}
            for declaration,kind,target,item in texts:
                if text==declaration:
                    return {'mode':'play','steps':[action(kind,target,item,utterance=text)]}
            raise AssertionError(text)
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            gm=make_condition_gm(engine,complete=complete)
            for index,(text,_,_,_) in enumerate(texts):
                with patch('kobold_rpg.condition_state_trial._dice',
                           return_value=lambda sides:20):
                    reply=gm(engine.state(),text,'http://none')
                engine.record_gm_reply(text,reply,'step-'+str(index),index)
                state=engine.state();door=state['world']['entities']['side_door']
                self.assertEqual(state['revision'],index+1)
                if index==0:
                    self.assertEqual(door['values']['integrity'],80)
                    self.assertIs(door['values']['locked'],True)
                    self.assertIs(door['values']['open'],False)
                elif index==1:
                    self.assertIs(door['values']['locked'],False)
                    self.assertIs(door['values']['open'],False)
                    self.assertIn('已解鎖',door['condition_sentence'])
                elif index==2:
                    self.assertIs(door['values']['open'],True)
                    self.assertIn('已打開',door['condition_sentence'])
                else:self.assertEqual(state['pc']['location'],'shelter')
            recent,_=recent_context(engine,engine.state())
            self.assertEqual([row['revision'] for row in recent],[1,2,3,4])
            self.assertTrue(engine.verify())

    def test_locked_door_cannot_be_opened_and_save_does_not_advance(self):
        seed=object_fixture();text='我推開側門。'
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            gm=make_condition_gm(engine,complete=lambda *args,**kwargs:
                {'mode':'play','steps':[action('open','side_door',utterance=text)]})
            with self.assertRaises(RuleError):gm(engine.state(),text,'http://none')
            self.assertEqual(engine.state()['revision'],0)
            self.assertIs(engine.state()['world']['entities']['side_door']['values']['open'],False)
            self.assertTrue(engine.verify())
