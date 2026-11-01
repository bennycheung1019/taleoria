import tempfile
import unittest
from pathlib import Path

from kobold_rpg.action_registry_trial import resolve, rules, validate_definition
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine, RuleError


def step(primitive, target_id=None, item_id=None, rule_id=None, utterance=None, goal=None, negated=False, difficulty=None):
    return {'primitive':primitive,'target_id':target_id,'item_id':item_id,'rule_id':rule_id,
            'utterance':utterance,'goal':goal,'negated':negated,'difficulty':difficulty}


def intent(steps, new_rule=None, mode='play'):
    return {'mode':mode,'steps':steps,'new_rule':new_rule}


def lock_rule(state):
    return {'id':'pick_lock','aliases':['撬鎖','開鎖'],'scope':state['campaign_id'],
            'operator':'set_entity_flag','required_capability':'開鎖',
            'required_item':'lockpick','required_flag':{'name':'locked','value':True},
            'roll':{'count':1,'sides':20,'modifier':2,'target':14},
            'effect':{'name':'locked','value':False},
            'basis':'此世界已建立普通鎖具和玩家的開鎖訓練；困難鎖使用 1d20+2 對 14。'}


def world():
    state=new_campaign()
    state['pc']['capabilities'].append('開鎖')
    state['pc']['inventory']['lockpick']=1
    state['world']={'background':'霧橋鎮','rules':[],
                    'entities':{'side_door':{'location':'gate','name':'側門','flags':{'locked':True,'open':False}}},
                    'action_rules':[]}
    return state


class RegistryTests(unittest.TestCase):
    def test_unknown_rule_can_be_validated_rolled_and_saved_per_world(self):
        state=world()
        proposal=intent([step('custom','side_door',rule_id='pick_lock')],lock_rule(state))
        calls=[]
        def die(sides):
            calls.append(sides)
            return 15
        decision=resolve(state,proposal,roller=die)
        self.assertEqual(calls,[20])
        self.assertEqual(decision['status'],'resolved')
        self.assertTrue(decision['rolls'][0]['success'])
        self.assertEqual(decision['changes']['world']['entities']['side_door']['flags']['locked'],False)
        self.assertTrue(state['world']['entities']['side_door']['flags']['locked'])
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=state)
            engine.record_gm_reply('我試吓用開鎖工具撬側門',
                {'narration':'鎖舌彈開，側門仍待你決定是否推開。','changes':decision['changes']},'lock-turn',0)
            saved=engine.state()
            self.assertEqual(saved['world']['entities']['side_door']['flags']['locked'],False)
            self.assertEqual(rules(saved)[0]['source_revision'],1)
            self.assertTrue(engine.verify())

    def test_reuse_rule_and_failed_roll_do_not_mutate_world(self):
        state=world();state['world']['action_rules']=[{**lock_rule(state),'source_revision':0}]
        decision=resolve(state,intent([step('custom','side_door',rule_id='pick_lock')]),roller=lambda sides:3)
        self.assertFalse(decision['rolls'][0]['success'])
        self.assertEqual(decision['changes'],{})
        self.assertEqual(state['world']['entities']['side_door']['flags']['locked'],True)

    def test_unknown_action_and_social_request_do_not_auto_succeed(self):
        state=world()
        decision=resolve(state,intent([step('speak','hark',utterance='請你放我入城'),
                                       step('custom','side_door',rule_id='invented')]))
        self.assertEqual([s['status'] for s in decision['steps']],['spoken','unresolved'])
        self.assertEqual(decision['status'],'needs_judgment')
        self.assertEqual(decision['changes'],{})

    def test_negation_movement_and_missing_power(self):
        state=world()
        decision=resolve(state,intent([step('move','shelter',negated=True),
                                       step('use_ability',rule_id='fireball')]))
        self.assertEqual(decision['steps'][0]['status'],'not_attempted')
        self.assertEqual(decision['steps'][1]['status'],'no_effect')
        self.assertEqual(decision['changes'],{})
        moved=resolve(state,intent([step('move','shelter')]))
        self.assertEqual(moved['changes']['pc']['location'],'shelter')

    def test_rule_cannot_create_power_or_duplicate_existing_definition(self):
        state=world();bad=lock_rule(state);bad['required_capability']='';bad['required_item']=''
        with self.assertRaises(RuleError):validate_definition(state,bad)
        state['world']['action_rules']=[{**lock_rule(state),'source_revision':0}]
        with self.assertRaises(RuleError):validate_definition(state,lock_rule(state))

    def test_ai_difficulty_varies_per_turn_and_is_checked_before_dice(self):
        state=world();state['world']['action_rules']=[{**lock_rule(state),'source_revision':0}]
        factor={'source_id':'entity:side_door','quote':'"locked": true',
                'impact':2,'reason':'已上鎖的鎖芯增加難度。'}
        easier={'base':10,'factors':[factor],'target':12}
        harder={'base':10,'factors':[{**factor,'impact':6}],'target':16}
        first=resolve(state,intent([step('custom','side_door',rule_id='pick_lock',difficulty=easier)]),roller=lambda sides:12)
        second=resolve(state,intent([step('custom','side_door',rule_id='pick_lock',difficulty=harder)]),roller=lambda sides:12)
        self.assertTrue(first['rolls'][0]['success'])
        self.assertFalse(second['rolls'][0]['success'])
        self.assertEqual(first['rolls'][0]['difficulty']['factors'][0]['source_id'],'entity:side_door')
        rolls=[]
        invalid={'base':10,'factors':[{**factor,'quote':'不存在的鎖芯'}],'target':12}
        with self.assertRaises(RuleError):
            resolve(state,intent([step('custom','side_door',rule_id='pick_lock',difficulty=invalid)]),
                    roller=lambda sides:rolls.append(sides) or 12)
        self.assertEqual(rolls,[])

    def test_mandatory_skill_and_tool_cannot_reduce_dc_twice(self):
        state=world();state['world']['action_rules']=[{**lock_rule(state),'source_revision':0}]
        difficulty={'base':10,'factors':[{'source_id':'pc.capabilities','quote':'開鎖',
            'impact':-2,'reason':'玩家懂開鎖'}],'target':8}
        rolls=[]
        with self.assertRaisesRegex(RuleError,'重複調整'):
            resolve(state,intent([step('custom','side_door',rule_id='pick_lock',
                                      difficulty=difficulty)]),
                    roller=lambda sides:rolls.append(sides) or 15)
        self.assertEqual(rolls,[])

    def test_ooc_never_advances_world(self):
        result=resolve(world(),intent([],mode='ooc'))
        self.assertEqual(result['status'],'ooc')
        self.assertEqual(result['changes'],{})


if __name__=='__main__':unittest.main()
