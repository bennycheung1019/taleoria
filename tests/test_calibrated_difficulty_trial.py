import copy
import tempfile
import unittest
from pathlib import Path

from kobold_rpg.calibrated_difficulty_trial import (MAX_SCENE_OBJECTS,
    compile_calibrated_action,propose_force_profile,register_force_profile,resolve_force,scene_context,
    trial_calibrated_turn)
from kobold_rpg.calibrated_pending_trial import prepare_calibrated_decision
from kobold_rpg.engine import Engine,RuleError
from test_dynamic_values_trial import object_fixture,object_proposal
from test_structured_state_trial import action


def profiled():
    state=object_fixture()
    return register_force_profile(state,'side_door','reinforced','breached',False,
                                  '厚木板和鐵箍','表面完整未有破口')


class CalibratedDifficultyTests(unittest.TestCase):
    def test_first_contact_learns_profile_then_reuses_it_after_failed_roll(self):
        seed=object_fixture();text='我試著撞破側門。';calls=[]
        intent={'mode':'play','steps':[action('force','side_door',utterance=text)]}
        profile={'tier':'reinforced','effect_key':'breached','initial':False,
                 'source_quote':'厚木板和鐵箍',
                 'initial_source_quote':'表面完整未有破口'}
        def complete(*args,**kwargs):
            calls.append(1);return intent if len(calls)==1 else profile
        first=trial_calibrated_turn(seed,text,'http://127.0.0.1:5001',complete,
                                    roller=lambda sides:19)
        self.assertEqual(len(calls),2)
        self.assertEqual(first['decision']['steps'][0]['status'],'failed')
        self.assertEqual(first['output_caps'],[450,160])
        saved_entity=first['decision']['changes']['world']['entities']['side_door']
        self.assertEqual(saved_entity['force_profile']['tier'],'reinforced')
        self.assertIs(saved_entity['values']['breached'],False)
        self.assertNotIn('force_profile',seed['world']['entities']['side_door'])
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            engine.record_gm_reply(text,{'narration':'門板仍然完整。',
                'changes':first['decision']['changes']},'first-force',0)
            saved=engine.state()
            self.assertEqual(saved['world']['entities']['side_door']['force_profile']['tier'],
                             'reinforced')
            next_turn=trial_calibrated_turn(saved,text,'http://127.0.0.1:5001',
                lambda *args,**kwargs:intent,roller=lambda sides:20)
            self.assertEqual(len(next_turn['input_tokens']),1)
            self.assertEqual(next_turn['decision']['rolls'][0]['target'],20)
            self.assertTrue(engine.verify())

    def test_scene_classifier_proposes_bounded_profile_without_changing_state(self):
        state=object_fixture();before=copy.deepcopy(state)
        proposal={'tier':'reinforced','effect_key':'breached','initial':False,
                  'source_quote':'厚木板和鐵箍',
                  'initial_source_quote':'表面完整未有破口'}
        picked,_=propose_force_profile(state,'side_door','http://127.0.0.1:5001',
                                       lambda *args,**kwargs:proposal)
        staged=register_force_profile(state,'side_door',picked['tier'],
            picked['effect_key'],picked['initial'],picked['source_quote'],
            picked['initial_source_quote'])
        self.assertEqual(state,before)
        self.assertEqual(staged['world']['entities']['side_door']['force_profile']['tier'],
                         'reinforced')
        bad={**proposal,'initial_source_quote':'玩家聲稱門早已破損'}
        with self.assertRaises(RuleError):register_force_profile(state,'side_door',
            bad['tier'],bad['effect_key'],bad['initial'],bad['source_quote'],
            bad['initial_source_quote'])

    def test_fixed_tier_and_actor_tool_bonus_do_not_reestimate_dc(self):
        state=profiled();before=copy.deepcopy(state)
        intent={'mode':'play','steps':[action('force','side_door')]}
        missed=resolve_force(state,intent,roller=lambda sides:19)
        self.assertEqual(missed['rolls'][0]['target'],20)
        self.assertEqual(missed['steps'][0]['status'],'failed')
        self.assertEqual(missed['changes'],{})
        repeated=resolve_force(state,intent,roller=lambda sides:19)
        self.assertEqual(repeated,missed)
        state['pc']['capabilities'].append('強力撞擊')
        state['pc']['inventory']['crowbar']=1
        intent['steps'][0]['item_id']='crowbar'
        succeeded=resolve_force(state,intent,roller=lambda sides:16)
        self.assertEqual((succeeded['rolls'][0]['base_dc'],
                          succeeded['rolls'][0]['capability_bonus'],
                          succeeded['rolls'][0]['tool_bonus'],
                          succeeded['rolls'][0]['total']),(20,2,2,20))
        door=succeeded['changes']['world']['entities']['side_door']['values']
        self.assertIs(door['breached'],True)
        self.assertIs(door['locked'],True)
        self.assertIs(door['open'],False)
        self.assertEqual(before['world']['entities']['side_door']['values']['breached'],False)
        state['world']['environment']['gate']['force_penalty']=3
        state['world']['environment_sources']['gate']['force_penalty']={
            'revision':0,'source':'雨中濕滑的地面'}
        harder=resolve_force(state,intent,roller=lambda sides:16)
        self.assertEqual(harder['rolls'][0]['target'],23)
        self.assertFalse(harder['rolls'][0]['success'])

    def test_unknown_profile_missing_tool_and_corrupt_profile_stop_safely(self):
        state=object_fixture();intent={'mode':'play','steps':[action('force','side_door')]}
        result=resolve_force(state,intent,roller=lambda sides:self.fail('must not roll'))
        self.assertEqual(result['steps'][0]['status'],'unresolved')
        state=profiled();intent['steps'][0]['item_id']='crowbar'
        result=resolve_force(state,intent,roller=lambda sides:self.fail('must not roll'))
        self.assertEqual(result['steps'][0]['status'],'no_effect')
        state['world']['entities']['side_door']['force_profile']['tier']='invented'
        intent['steps'][0]['item_id']=None
        with self.assertRaises(RuleError):
            resolve_force(state,intent,roller=lambda sides:self.fail('must not roll'))

    def test_only_established_object_evidence_can_create_profile(self):
        state=object_fixture();before=copy.deepcopy(state)
        with self.assertRaises(RuleError):
            register_force_profile(state,'side_door','reinforced','breached',False,
                                   '玩家說這道門很脆弱','表面完整未有破口')
        with self.assertRaises(RuleError):
            register_force_profile(state,'side_door','unknown','breached',False,
                                   '厚木板和鐵箍','表面完整未有破口')
        self.assertEqual(state,before)

    def test_crowded_scene_keeps_explicit_focus_and_fails_without_unique_focus(self):
        state=profiled();base=state['world']['entities']['side_door']
        for i in range(MAX_SCENE_OBJECTS+5):
            clone=copy.deepcopy(base);clone.pop('force_profile')
            state['world']['entities'][f'crate_{i:03d}']={**clone,'name':f'箱子 {i:03d}'}
        selected=scene_context(state,'我撞破側門')
        self.assertEqual(len(selected['objects']),1)
        self.assertIn('side_door',selected['objects'])
        self.assertNotIn('values',selected['objects']['side_door'])
        distant=scene_context(state,'我撞破箱子 024')
        self.assertIn('crate_024',distant['objects'])
        with self.assertRaises(RuleError):scene_context(state,'我碰碰那個東西')

    def test_scene_profile_cap_does_not_delete_other_world_objects(self):
        state=object_fixture();template=state['world']['entities']['side_door']
        for i in range(MAX_SCENE_OBJECTS):
            key=f'door_{i:03d}';entity=copy.deepcopy(template)
            entity['name']=f'側門 {i:03d}'
            state['world']['entities'][key]=entity
        for i in range(MAX_SCENE_OBJECTS):
            state=register_force_profile(state,f'door_{i:03d}',
                'reinforced','breached',False,'厚木板和鐵箍','表面完整未有破口')
        with self.assertRaises(RuleError):
            register_force_profile(state,'side_door','reinforced','breached',False,
                                   '厚木板和鐵箍','表面完整未有破口')
        self.assertIn('side_door',state['world']['entities'])

    def test_compact_intent_uses_one_model_call_and_custom_fallback_remains(self):
        state=profiled();text='我試著撞破側門。';calls=[]
        intent={'mode':'play','steps':[action('force','side_door',utterance=text)]}
        def complete(messages,*args,**kwargs):
            calls.append(messages)
            return intent
        result=trial_calibrated_turn(state,text,'http://127.0.0.1:5001',complete,
                                     roller=lambda sides:20)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(result['input_tokens']),1)
        self.assertTrue(result['decision']['rolls'][0]['success'])
        self.assertNotIn('lock_dc',str(calls[0]))
        self.assertEqual(scene_context(state,text)['inventory_names'],[])
        def invented_tool(messages,*args,**kwargs):
            return {'mode':'play','steps':[action('force','side_door',
                                               item='hunting_knife',utterance=text)]}
        cleaned=trial_calibrated_turn(state,text,'http://127.0.0.1:5001',
                                     invented_tool,roller=lambda sides:20)
        self.assertIsNone(cleaned['intent']['steps'][0]['item_id'])
        self.assertEqual(cleaned['decision']['rolls'][0]['tool_bonus'],0)
        original=object_fixture();fallback=[];custom_text='我試著推倒側門。'
        def custom(messages,*args,**kwargs):
            fallback.append(messages)
            return ({'mode':'play','steps':[action('custom','side_door',utterance=custom_text)]}
                    if len(fallback)==1 else object_proposal())
        result=trial_calibrated_turn(original,custom_text,'http://127.0.0.1:5001',custom,
                                     roller=lambda sides:20)
        self.assertEqual(len(fallback),2)
        self.assertEqual(len(result['input_tokens']),2)

    def test_fixed_result_persists_in_disposable_sqlite(self):
        seed=profiled();decision=resolve_force(seed,{'mode':'play','steps':[
            action('force','side_door')]},roller=lambda sides:20)
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            reply={'narration':'側門出現破口，但仍然上鎖及關閉。',
                   'changes':decision['changes']}
            first=engine.record_gm_reply('我撞破側門',reply,'force-once',0)
            second=engine.record_gm_reply('我撞破側門',reply,'force-once',0)
            self.assertEqual(first,second)
            saved=engine.state()
            self.assertEqual(saved['revision'],1)
            self.assertIs(saved['world']['entities']['side_door']['values']['breached'],True)
            self.assertIs(saved['world']['entities']['side_door']['values']['open'],False)
            self.assertTrue(engine.verify())

    def test_retry_keeps_one_frozen_calibrated_roll(self):
        seed=profiled();text='我試著撞破側門。';calls=[]
        intent={'mode':'play','steps':[action('force','side_door',utterance=text)]}
        def complete(*args,**kwargs):
            calls.append(1);return intent
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            first=prepare_calibrated_decision(engine,'request-1',0,text,
                                              'http://127.0.0.1:5001',complete)
            retry=prepare_calibrated_decision(engine,'request-1',0,text,
                'http://127.0.0.1:5001',
                lambda *args,**kwargs:self.fail('retry must not call model'))
            self.assertEqual(first,retry)
            self.assertEqual(len(calls),1)
            self.assertEqual(engine.state(),seed)
            with self.assertRaises(RuleError):
                prepare_calibrated_decision(engine,'request-1',0,'我離開。',
                                            'http://127.0.0.1:5001',complete)

    def test_first_contact_retry_reuses_saved_profile_and_roll(self):
        seed=object_fixture();text='我試著撞破側門。';calls=[]
        intent={'mode':'play','steps':[action('force','side_door',utterance=text)]}
        profile={'tier':'reinforced','effect_key':'breached','initial':False,
                 'source_quote':'厚木板和鐵箍',
                 'initial_source_quote':'表面完整未有破口'}
        def complete(*args,**kwargs):
            calls.append(1);return intent if len(calls)==1 else profile
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            first=prepare_calibrated_decision(engine,'new-object',0,text,
                                              'http://127.0.0.1:5001',complete)
            retry=prepare_calibrated_decision(engine,'new-object',0,text,
                'http://127.0.0.1:5001',
                lambda *args,**kwargs:self.fail('retry must not call model'))
            self.assertEqual(first,retry)
            self.assertEqual(len(calls),2)
            self.assertEqual(first['decision']['rolls'][0]['target'],20)
            self.assertEqual(engine.state(),seed)
            self.assertTrue(engine.verify())


if __name__=='__main__':unittest.main()
