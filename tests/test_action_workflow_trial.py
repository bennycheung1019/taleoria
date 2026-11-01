import json
import unittest
from unittest.mock import patch

from kobold_rpg.action_workflow_trial import trial_turn
from kobold_rpg.action_workflow_trial import compile_intent
from kobold_rpg.action_workflow_trial import audit_narration
from kobold_rpg.engine import RuleError
from test_action_registry_trial import intent,lock_rule,step,world


def door_difficulty():
    return {'base':10,'factors':[{'source_id':'entity:side_door',
        'quote':'"locked": true','impact':2,'reason':'門已上鎖，需處理鎖芯。'}],
        'target':12}


class ActionWorkflowTests(unittest.TestCase):
    @patch('kobold_rpg.action_workflow_trial.count',return_value=None)
    @patch('kobold_rpg.action_workflow_trial.budget',return_value=None)
    def test_compound_intent_rolls_once_and_narrates_frozen_result(self,*_):
        state=world();before=json.dumps(state,ensure_ascii=False,sort_keys=True)
        parsed=intent([step('observe','side_door'),step('custom','side_door',rule_id='pick_lock',
                                                    difficulty=door_difficulty())],lock_rule(state))
        calls=[]
        def fake(messages,*_args,**_kwargs):
            calls.append(messages)
            if len(calls)==1:return json.dumps(parsed,ensure_ascii=False)
            if len(calls)==3:return json.dumps({'consistent':True,'conflicts':[],
                                                'added_pc_actions':[],'unsupported_facts':[]})
            payload=json.loads(messages[0]['content'].split('\n',1)[1])
            self.assertTrue(payload['host_result']['rolls'][0]['success'])
            return json.dumps({'decision_id':payload['decision_id'],
                               'narration':'你檢查側門後試著撬鎖；鎖舌彈開，門仍待你決定是否推開。'},ensure_ascii=False)
        die=[]
        def roller(sides):die.append(sides);return 15
        result=trial_turn(state,'我先看側門，再用開鎖工具試著撬鎖','http://none',fake,roller)
        self.assertEqual(len(calls),3)
        self.assertEqual(die,[20])
        self.assertEqual(result['decision']['changes']['world']['entities']['side_door']['flags']['locked'],False)
        self.assertEqual(json.dumps(state,ensure_ascii=False,sort_keys=True),before)

    @patch('kobold_rpg.action_workflow_trial.count',return_value=None)
    @patch('kobold_rpg.action_workflow_trial.budget',return_value=None)
    def test_narrator_must_echo_decision_id_before_commit(self,*_):
        parsed=intent([step('move','shelter')])
        calls=[]
        def fake(messages,*_args,**_kwargs):
            calls.append(messages)
            return json.dumps(parsed if len(calls)==1 else
                              {'decision_id':'wrong','narration':'你到了避雨棚。'},ensure_ascii=False)
        with self.assertRaises(RuleError):trial_turn(world(),'我去避雨棚','http://none',fake)
        self.assertEqual(len(calls),2)

    @patch('kobold_rpg.action_workflow_trial.count',return_value=None)
    @patch('kobold_rpg.action_workflow_trial.budget',return_value=None)
    def test_existing_tool_action_is_reconciled_without_granting_power(self,*_):
        state=world();rule=lock_rule(state)
        rule['id']='new_action';rule['required_flag']['value']=False
        parsed=intent([step('use_ability','side_door',item_id='lockpick',difficulty=door_difficulty())],rule)
        compiled,_=compile_intent(state,'用開鎖工具撬鎖','http://none',
                                  complete=lambda *_args,**_kwargs:json.dumps(parsed,ensure_ascii=False))
        self.assertEqual(compiled['steps'][0]['primitive'],'custom')
        self.assertEqual(compiled['steps'][0]['rule_id'],compiled['new_rule']['id'])
        self.assertEqual(compiled['new_rule']['required_flag']['value'],True)

    @patch('kobold_rpg.action_workflow_trial.count',return_value=None)
    @patch('kobold_rpg.action_workflow_trial.budget',return_value=None)
    def test_rule_for_speech_or_unattempted_thought_is_not_installed(self,*_):
        state=world();rule=lock_rule(state);rule['id']='new_action'
        for steps in ([step('speak','hark',rule_id='new_action',utterance='請放行')],
                      [step('speak','hark',utterance='幾點？'),
                       step('custom','side_door',goal='只係心諗',negated=True)]):
            parsed=intent(steps,rule)
            compiled,_=compile_intent(state,'只係講嘢','http://none',
                                      complete=lambda *_args,**_kwargs:json.dumps(parsed,ensure_ascii=False))
            self.assertIsNone(compiled['new_rule'])

    @patch('kobold_rpg.action_workflow_trial.count',return_value=None)
    @patch('kobold_rpg.action_workflow_trial.budget',return_value=None)
    def test_existing_rule_id_is_reused_despite_extra_definition(self,*_):
        state=world();state['world']['action_rules']=[{**lock_rule(state),'source_revision':0}]
        duplicate=lock_rule(state);duplicate['id']='new_action';duplicate['aliases']=[]
        parsed=intent([step('move','side_door',rule_id='pick_lock',difficulty=door_difficulty())],duplicate)
        compiled,_=compile_intent(state,'用開鎖工具撬鎖','http://none',
                                  complete=lambda *_args,**_kwargs:json.dumps(parsed,ensure_ascii=False))
        self.assertEqual(compiled['steps'][0]['primitive'],'custom')
        self.assertEqual(compiled['steps'][0]['rule_id'],'pick_lock')
        self.assertIsNone(compiled['new_rule'])

    @patch('kobold_rpg.action_workflow_trial.count',return_value=None)
    @patch('kobold_rpg.action_workflow_trial.budget',return_value=None)
    def test_missing_difficulty_gets_one_focused_call_before_roll(self,*_):
        state=world();parsed=intent([step('custom','side_door',item_id='lockpick',rule_id='pick_lock')],lock_rule(state))
        calls=[];rolled=[]
        def fake(messages,*_args,**_kwargs):
            calls.append(messages)
            if len(calls)==1:return json.dumps(parsed,ensure_ascii=False)
            if len(calls)==2:return json.dumps({'factors':[{'source_id':'entity:side_door.flag.locked',
                'impact':2,'reason':'門已上鎖，增加難度。'}]},ensure_ascii=False)
            if len(calls)==4:return json.dumps({'consistent':True,'conflicts':[],
                                                'added_pc_actions':[],'unsupported_facts':[]})
            payload=json.loads(messages[0]['content'].split('\n',1)[1])
            return json.dumps({'decision_id':payload['decision_id'],'narration':'鎖扣已解開，門仍關著。'},ensure_ascii=False)
        result=trial_turn(state,'我試用開鎖工具撬鎖','http://none',fake,
                          roller=lambda sides:rolled.append(sides) or 15)
        self.assertEqual(len(calls),4)
        self.assertEqual(rolled,[20])
        self.assertEqual(result['decision']['rolls'][0]['target'],12)

    @patch('kobold_rpg.action_workflow_trial.count',return_value=None)
    @patch('kobold_rpg.action_workflow_trial.budget',return_value=None)
    def test_auditor_rejects_unresolved_door_opening(self,*_):
        state=world();decision={'status':'resolved','steps':[],
            'changes':{'world':{'entities':{'side_door':{'location':'gate','name':'側門',
                'flags':{'locked':False,'open':False}}}}},'rolls':[]}
        finding={'consistent':False,'conflicts':['門仍關著，敘事卻說門縫微啟'],
                 'added_pc_actions':[],'unsupported_facts':[]}
        with self.assertRaisesRegex(RuleError,'門已打開'):
            audit_narration(state,'我試撬鎖',decision,'門縫微啟。','http://none',
                            complete=lambda *_a,**_k:json.dumps(finding,ensure_ascii=False))


if __name__=='__main__':unittest.main()
