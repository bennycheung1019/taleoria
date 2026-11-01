import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kobold_rpg.dynamic_pending_trial import prepare_dynamic_decision
from kobold_rpg.dynamic_values_trial import (register_npc_attribute,
    register_object_extension,trial_dynamic_turn)
from kobold_rpg.engine import Engine,RuleError
from kobold_rpg.social_values_trial import resolve_social
from kobold_rpg.structured_state_trial import resolve_values
from kobold_rpg.structured_state_trial import relevant_context
from test_social_values_trial import fixture
from test_structured_state_trial import action


def object_fixture():
    state=fixture()
    state['world']['entities']['side_door']['description']='側門由厚木板和鐵箍做成，表面完整未有破口。'
    return state


def object_proposal():
    return {'action_id':'breach_door','label':'撞破側門',
        'target_id':'side_door','target_type':'door',
        'difficulty':{'id':'breach_dc','label':'撞破難度','value':16,
            'source_quote':'厚木板和鐵箍','reason':'門板與鐵箍增加阻力。'},
        'effect':{'id':'breached','label':'已有破口','initial':False,
            'on_success':True,'source_quote':'表面完整未有破口',
            'reason':'目前未有破口，成功後改為有破口。'},
        'operator':'check_and_set_boolean'}


def emotion_fixture():
    state=fixture()
    state['world']['confirmed_events']={'brother_fell':{
        'text':'哈克親眼看見弟弟倒在雨中，悲傷湧上心頭。',
        'participants':['hark'],'revision':0}}
    return state


def emotion_proposal():
    return {'kind':'emotion','label':'悲傷','initial_value':8,
        'source_quote':'悲傷湧上心頭','reason':'親人遇事帶來強烈悲傷。',
        'effects':[{'contract_id':'shift_question','direction':'resist','weight':1}]}


class DynamicValueTests(unittest.TestCase):
    def test_invalid_model_initial_value_gets_one_bounded_repair(self):
        state=object_fixture();before=copy.deepcopy(state);text='我試著撞破側門。'
        intent={'mode':'play','steps':[action('custom','side_door',utterance=text)]}
        invalid=object_proposal();invalid['effect']['initial']=True
        seen=[]
        def complete(messages,*args,**kwargs):
            seen.append(messages)
            return (intent,invalid,object_proposal())[len(seen)-1]
        result=trial_dynamic_turn(state,text,'http://127.0.0.1:5001',complete,
                                  roller=lambda sides:17)
        self.assertEqual(len(seen),3)
        self.assertIn('上次提案未通過程式驗證',seen[2][1]['content'])
        self.assertTrue(result['decision']['rolls'][0]['success'])
        self.assertEqual(state,before)
        with self.assertRaises(RuleError):
            trial_dynamic_turn(state,text,'http://127.0.0.1:5001',
                lambda messages,*args,**kwargs:intent if len(messages)==2 else invalid,
                roller=lambda sides:self.fail('invalid proposal must not roll'))

    def test_same_request_reuses_frozen_dynamic_decision_without_new_model_or_die(self):
        state=object_fixture();text='我試著撞破側門。';calls=[]
        intent={'mode':'play','steps':[action('custom','side_door',utterance=text)]}
        def complete(*args,**kwargs):
            calls.append(1)
            return intent if len(calls)==1 else object_proposal()
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=state)
            first=prepare_dynamic_decision(engine,'same',0,text,'http://127.0.0.1:5001',complete)
            second=prepare_dynamic_decision(engine,'same',0,text,'http://127.0.0.1:5001',
                lambda *args,**kwargs:self.fail('retry must not call model'))
            self.assertEqual(first,second)
            self.assertEqual(len(calls),2)
            self.assertEqual(first['decision']['rolls'][0]['die'],second['decision']['rolls'][0]['die'])
            self.assertEqual(engine.state(),state)
            self.assertTrue(engine.verify())
            with self.assertRaises(RuleError):
                prepare_dynamic_decision(engine,'same',0,'我想離開。','http://127.0.0.1:5001',complete)
            engine.record_gm_reply('測試轉移',{'narration':'測試轉移','changes':{}},'other',0)
            with self.assertRaises(RuleError):
                prepare_dynamic_decision(engine,'same',0,text,'http://127.0.0.1:5001',complete)

    def test_retry_after_model_or_resolver_interruption_reuses_saved_stages(self):
        state=object_fixture();text='我試著撞破側門。'
        intent={'mode':'play','steps':[action('custom','side_door',utterance=text)]}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=state)
            calls=[]
            def fails_at_proposal(*args,**kwargs):
                calls.append(1)
                if len(calls)==1:return intent
                raise RuntimeError('simulated interrupted model call')
            with self.assertRaises(RuntimeError):
                prepare_dynamic_decision(engine,'interrupted',0,text,
                                         'http://127.0.0.1:5001',fails_at_proposal)
            with patch('kobold_rpg.dynamic_pending_trial.resolve_dynamic_intent',
                       side_effect=RuntimeError('simulated interruption after proposal')):
                with self.assertRaises(RuntimeError):
                    prepare_dynamic_decision(engine,'interrupted',0,text,
                        'http://127.0.0.1:5001',lambda *args,**kwargs:object_proposal())
            result=prepare_dynamic_decision(engine,'interrupted',0,text,
                'http://127.0.0.1:5001',
                lambda *args,**kwargs:self.fail('saved intent/proposal must be reused'))
            self.assertEqual(len(calls),2)
            self.assertEqual(result['proposal']['difficulty']['value'],16)
            self.assertEqual(len(result['decision']['rolls']),1)
            self.assertEqual(engine.state(),state)
            self.assertTrue(engine.verify())

    def test_new_door_attribute_and_action_stay_distinct_from_open(self):
        state=object_fixture();before=copy.deepcopy(state)
        staged=register_object_extension(state,object_proposal())
        self.assertEqual(state,before)
        entity=staged['world']['entities']['side_door']
        self.assertEqual(entity['values']['breach_dc'],16)
        self.assertIs(entity['values']['breached'],False)
        self.assertIs(entity['values']['open'],False)
        intent={'mode':'play','steps':[action('breach_door','side_door')]}
        decision=resolve_values(staged,intent,roller=lambda sides:17)
        self.assertTrue(decision['rolls'][0]['success'])
        self.assertIs(decision['changes']['world']['entities']['side_door']['values']['breached'],True)
        self.assertIs(decision['changes']['world']['entities']['side_door']['values']['open'],False)
        self.assertIs(decision['changes']['world']['entities']['side_door']['values']['locked'],True)

    def test_unestablished_door_weakness_is_rejected_before_dice(self):
        state=object_fixture();proposal=object_proposal()
        proposal['difficulty']['source_quote']='玩家說這道門很脆弱'
        with self.assertRaises(RuleError):register_object_extension(state,proposal)
        self.assertNotIn('breach_dc',state['world']['entities']['side_door']['values'])
        state['world']['entities']['other_door']=copy.deepcopy(state['world']['entities']['side_door'])
        state['world']['entities']['other_door']['description']='另一道門由薄木板製成。'
        proposal=object_proposal();proposal['difficulty']['source_quote']='薄木板'
        with self.assertRaises(RuleError):register_object_extension(state,proposal)

    def test_generic_room_or_unrelated_public_fact_cannot_define_door_strength(self):
        state=object_fixture()
        state['world']['entities']['side_door']['description']=''
        state['locations'][state['pc']['location']]['description']='雨水打濕石路，附近有些薄木板。'
        state['facts']=[{'text':'另一扇門由薄木板製成。','visibility':'public'}]
        proposal=object_proposal()
        proposal['difficulty']['source_quote']='薄木板'
        proposal['effect']['source_quote']='雨水打濕石路'
        with self.assertRaises(RuleError):register_object_extension(state,proposal)
        self.assertNotIn('breach_dc',state['world']['entities']['side_door']['values'])
        state['locations'][state['pc']['location']]['description']='側門仍然關著。旁邊有些薄木板。'
        state['facts']=[{'text':'側門仍然關著。附近的雨水令地面濕滑。','visibility':'public'}]
        proposal['effect']['source_quote']='側門仍然關著'
        with self.assertRaises(RuleError):register_object_extension(state,proposal)

    def test_one_character_quote_is_not_sufficient_evidence(self):
        state=object_fixture();proposal=object_proposal()
        proposal['difficulty']['source_quote']='門'
        with self.assertRaises(RuleError):register_object_extension(state,proposal)

    def test_corrupt_saved_dynamic_rule_stops_before_dice(self):
        state=register_object_extension(object_fixture(),object_proposal())
        state['world']['dynamic_actions']['breach_door']['effect_value']='yes'
        with self.assertRaises(RuleError):
            resolve_values(state,{'mode':'play','steps':[action('breach_door','side_door')]},
                           roller=lambda sides:self.fail('must not roll'))

    def test_action_id_collision_is_normalized_and_reusable(self):
        state=object_fixture();proposal=object_proposal();proposal['action_id']='breach_dc'
        staged=register_object_extension(state,proposal)
        self.assertIn('action_1_1',staged['world']['dynamic_actions'])
        self.assertIn('action_1_1',relevant_context(staged)['available_actions'])
        self.assertIn('尚未由物理規則獨立校準',
                      staged['world']['attribute_definitions']['door.breach_dc']['reason'])
        result=resolve_values(staged,{'mode':'play','steps':[action('action_1_1','side_door')]},
                              roller=lambda sides:17)
        self.assertTrue(result['rolls'][0]['success'])
        self.assertIn('其他狀態不變',staged['world']['attribute_definitions']['door.breached']['reason'])
        staged['world']['entities']['side_door']['values']['breach_dc']=100
        with self.assertRaises(RuleError):resolve_values(staged,{'mode':'play','steps':[
            action('action_1_1','side_door')]},roller=lambda sides:self.fail('must not roll'))

    def test_new_emotion_requires_confirmed_event_and_changes_next_social_dc(self):
        state=emotion_fixture();choice={'contract_id':'shift_question','selected_factor_ids':[]}
        before=resolve_social(state,'hark',choice,roller=lambda sides:13)
        changed=register_npc_attribute(state,'hark','brother_fell',emotion_proposal())
        after=resolve_social(changed,'hark',choice,roller=lambda sides:13)
        self.assertEqual((before['rolls'][0]['target'],after['rolls'][0]['target']),(13,16))
        self.assertEqual((before['status'],after['status']),('succeeded','refused'))
        self.assertEqual(changed['npcs']['hark']['social_state']['values']['emotion.event_1_1'],8)
        self.assertEqual(changed['world']['social_attribute_definitions']['emotion.event_1_1']['source_event'],
                         'brother_fell')
        self.assertNotIn('emotion.event_1_1',state['npcs']['hark']['social_state']['values'])
        with self.assertRaises(RuleError):
            register_npc_attribute(state,'hark','player_claimed_brother_fell',emotion_proposal())

    def test_unrelated_or_fake_emotion_evidence_is_rejected(self):
        state=emotion_fixture();proposal=emotion_proposal()
        proposal['source_quote']='玩家說哈克很悲傷'
        with self.assertRaises(RuleError):register_npc_attribute(state,'hark','brother_fell',proposal)
        proposal=emotion_proposal();proposal['effects'][0]['contract_id']='not_a_rule'
        with self.assertRaises(RuleError):register_npc_attribute(state,'hark','brother_fell',proposal)
        state=emotion_fixture();state['world']['confirmed_events']['brother_fell']['revision']=9
        with self.assertRaises(RuleError):register_npc_attribute(state,'hark','brother_fell',emotion_proposal())

    def test_staged_extension_and_effect_can_commit_to_disposable_sqlite(self):
        state=object_fixture();staged=register_object_extension(state,object_proposal())
        decision=resolve_values(staged,{'mode':'play','steps':[action('breach_door','side_door')]},
                                roller=lambda sides:17)
        changes=decision['changes'];world=changes['world']
        world['attribute_definitions']=staged['world']['attribute_definitions']
        world['dynamic_actions']=staged['world']['dynamic_actions']
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=state)
            reply={'narration':'撞擊造成門板破口；門仍上鎖且未打開。','changes':changes}
            engine.record_gm_reply('我試著撞破側門',reply,'breach-once',0)
            saved=engine.state()
            self.assertIs(saved['world']['entities']['side_door']['values']['breached'],True)
            self.assertIs(saved['world']['entities']['side_door']['values']['open'],False)
            self.assertIn('breach_door',saved['world']['dynamic_actions'])
            self.assertTrue(engine.verify())

    def test_new_emotion_and_contract_link_persist_to_disposable_sqlite(self):
        state=emotion_fixture();staged=register_npc_attribute(
            state,'hark','brother_fell',emotion_proposal())
        changes={'npcs':{'hark':{'social_state':staged['npcs']['hark']['social_state']}},
                 'world':{'social_attribute_definitions':staged['world']['social_attribute_definitions'],
                          'social_contracts':staged['world']['social_contracts']}}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=state)
            engine.record_gm_reply('已確認哈克的悲傷',{'narration':'哈克在雨中目睹弟弟倒下。',
                'changes':changes},'grief-once',0)
            saved=engine.state()
            self.assertEqual(saved['npcs']['hark']['social_state']['values']['emotion.event_1_1'],8)
            self.assertIn('emotion.event_1_1',[row['id'] for row in
                saved['world']['social_contracts']['shift_question']['factors']])
            self.assertTrue(engine.verify())


if __name__=='__main__':unittest.main()
