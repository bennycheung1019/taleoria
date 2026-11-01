import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine,RuleError
from kobold_rpg.structured_state_trial import (compile_action, relevant_context,
                                                resolve_values, validate_values,
                                                trial_turn, register_door,
                                                render_host_narration)


def fixture():
    state=new_campaign();state['pc']['capabilities'].append('開鎖')
    state['pc']['inventory']['lockpick']=1
    values={'locked':True,'open':False,'jammed':False,'lock_dc':14}
    state['world']={'background':'完整背景文字仍保留於存檔',
                    'entities':{'side_door':{'name':'側門','type':'door','location':'gate',
                        'values':values,'value_sources':{name:{'revision':0,'source':'scene setup'}
                                                          for name in values}}},
                    'environment':{'gate':{'heat_c':22,'visibility':80,'danger':2}},
                    'environment_sources':{'gate':{name:{'revision':0,'source':'scene setup'}
                                                    for name in ('heat_c','visibility','danger')}}}
    state['npcs']['hark']['metrics']={'anger':2,'trust':3}
    state['npcs']['hark']['metric_sources']={name:{'revision':0,'source':'initial encounter'}
                                             for name in ('anger','trust')}
    return state


def action(kind,target=None,item=None,utterance=None,negated=False,requires_previous_success=False):
    return {'action':kind,'target_id':target,'item_id':item,
            'utterance':utterance,'negated':negated,
            'requires_previous_success':requires_previous_success}


class StructuredStateTests(unittest.TestCase):
    def test_new_door_records_known_values_and_preserves_unknowns(self):
        original=fixture()
        created=register_door(original,'iron_door','鐵門','gate','scene event:1',
                              locked=True,open=False)
        self.assertNotIn('iron_door',original['world']['entities'])
        values=created['world']['entities']['iron_door']['values']
        self.assertIs(values['locked'],True)
        self.assertIs(values['open'],False)
        self.assertIsNone(values['lock_dc'])
        self.assertNotIn('lock_dc',created['world']['entities']['iron_door']['value_sources'])
        result=resolve_values(created,{'mode':'play','steps':[action('unlock','iron_door','lockpick')]})
        self.assertEqual(result['steps'][0]['status'],'unresolved')

    def test_ooc_is_not_misrendered_as_a_game_action(self):
        decision=resolve_values(fixture(),{'mode':'ooc','steps':[]})
        self.assertIsNone(render_host_narration(fixture(),decision))

    def test_unlock_and_open_are_distinct_state_transitions(self):
        state=fixture();before=copy.deepcopy(state)
        result=resolve_values(state,{'mode':'play','steps':[action('unlock','side_door','lockpick')]},
                              roller=lambda sides:15)
        self.assertTrue(result['rolls'][0]['success'])
        self.assertEqual(result['rolls'][0]['target'],14)
        self.assertIs(result['changes']['world']['entities']['side_door']['values']['locked'],False)
        self.assertIs(result['changes']['world']['entities']['side_door']['values']['open'],False)
        self.assertEqual(state,before)
        state['world']['entities']['side_door']=result['changes']['world']['entities']['side_door']
        opened=resolve_values(state,{'mode':'play','steps':[action('open','side_door')]},
                              roller=lambda sides:self.fail('opening should not roll'))
        self.assertIs(opened['changes']['world']['entities']['side_door']['values']['open'],True)

    def test_decision_persists_once_in_disposable_sqlite_save(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=fixture())
            state=engine.state()
            decision=resolve_values(state,{'mode':'play','steps':[
                action('unlock','side_door','lockpick')]},roller=lambda sides:15)
            from kobold_rpg.structured_state_trial import render_host_narration
            reply={'narration':render_host_narration(state,decision),
                   'changes':decision['changes']}
            first=engine.record_gm_reply('我試撬側門',reply,'structured-lock',0)
            second=engine.record_gm_reply('我試撬側門',reply,'structured-lock',0)
            saved=engine.state()
            self.assertEqual(first,second)
            self.assertEqual(saved['revision'],1)
            self.assertIs(saved['world']['entities']['side_door']['values']['locked'],False)
            self.assertIs(saved['world']['entities']['side_door']['values']['open'],False)
            self.assertEqual(saved['world']['entities']['side_door']['value_sources']['locked']['revision'],1)
            self.assertTrue(engine.verify())

    def test_environment_changes_dc_without_ai_assessment(self):
        clear=fixture();adverse=fixture()
        adverse['world']['environment']['gate'].update(heat_c=42,visibility=25)
        step={'mode':'play','steps':[action('unlock','side_door','lockpick')]}
        first=resolve_values(clear,step,roller=lambda sides:15)
        second=resolve_values(adverse,step,roller=lambda sides:15)
        self.assertTrue(first['rolls'][0]['success'])
        self.assertFalse(second['rolls'][0]['success'])
        self.assertEqual(second['rolls'][0]['target'],18)
        self.assertEqual([f['source'] for f in second['rolls'][0]['factors']],
                         ['environment.visibility','environment.heat_c'])
        self.assertEqual(second['changes'],{})

    def test_conditional_followup_is_skipped_after_failed_roll(self):
        state=fixture()
        sequence={'mode':'play','steps':[action('unlock','side_door','lockpick'),
            action('open','side_door',requires_previous_success=True)]}
        result=resolve_values(state,sequence,roller=lambda sides:2)
        self.assertEqual([row['status'] for row in result['steps']],['failed','not_attempted'])
        self.assertEqual(result['changes'],{})

    def test_unknown_is_not_false_and_social_scores_do_not_force_consent(self):
        state=fixture();entity=state['world']['entities']['side_door']
        entity['values']['locked']=None
        entity['value_sources'].pop('locked')
        self.assertEqual(resolve_values(state,{'mode':'play','steps':[
            action('unlock','side_door','lockpick')]})['steps'][0]['status'],'unresolved')
        state['npcs']['hark']['metrics']={'anger':0,'trust':10}
        social=resolve_values(state,{'mode':'play','steps':[
            action('persuade','hark',utterance='請放行')]})
        self.assertEqual(social['status'],'needs_judgment')
        self.assertEqual(social['changes'],{})

    def test_invalid_or_unsourced_values_are_rejected(self):
        state=fixture();entity=state['world']['entities']['side_door']
        entity['value_sources'].pop('locked')
        with self.assertRaises(RuleError):validate_values(state)
        entity['value_sources']['locked']={'revision':0,'source':'scene setup'}
        state['world']['environment']['gate']['visibility']=150
        with self.assertRaises(RuleError):validate_values(state)
        state['world']['environment']['gate']['visibility']=80
        state['npcs']['hark']['metric_sources'].pop('trust')
        with self.assertRaises(RuleError):validate_values(state)

    @patch('kobold_rpg.structured_state_trial.count',return_value=None)
    @patch('kobold_rpg.structured_state_trial.budget',return_value=None)
    def test_ai_only_compiles_intent_from_relevant_values(self,*_):
        state=fixture();state['recent_dialogue']=['守衛：側門仍關著。']
        context=relevant_context(state)
        self.assertEqual(context['objects']['side_door']['values']['lock_dc'],14)
        self.assertNotIn('完整背景文字',json.dumps(context,ensure_ascii=False))
        expected={'mode':'play','steps':[action('unlock','side_door','lockpick')]}
        intent,_=compile_action(state,'我用開鎖工具試撬側門','http://none',
                                complete=lambda *_a,**_k:json.dumps(expected,ensure_ascii=False))
        self.assertEqual(intent,expected)

    @patch('kobold_rpg.structured_state_trial.count',return_value=None)
    @patch('kobold_rpg.structured_state_trial.budget',return_value=None)
    def test_mechanical_narration_cannot_open_a_still_closed_door(self,*_):
        state=fixture();calls=[]
        parsed={'mode':'play','steps':[action('observe','side_door'),
                                      action('unlock','side_door','lockpick')]}
        def complete(*_args,**_kwargs):
            calls.append(1)
            return json.dumps(parsed,ensure_ascii=False)
        result=trial_turn(state,'我先看側門，再試撬鎖','http://none',complete,
                          roller=lambda sides:15)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['narration_source'],'host')
        self.assertIn('鎖已解開',result['narration'])
        self.assertIn('仍關著',result['narration'])
        self.assertIs(result['decision']['changes']['world']['entities']['side_door']['values']['open'],False)


if __name__=='__main__':unittest.main()
