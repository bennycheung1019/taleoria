import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kobold_rpg.engine import Engine,RuleError
from kobold_rpg.social_values_trial import (resolve_social,select_social_context,
                                            trial_social_turn,validate_social,
                                            register_social_contract,
                                            apply_social_event,render_social)
from test_structured_state_trial import action,fixture as physical_fixture


def fixture():
    state=physical_fixture();state['pc']['capabilities'].append('交涉')
    npc=state['npcs']['hark'];npc['metrics']={};npc['metric_sources']={}
    values={'emotion.anger':2,'emotion.fear':1,'emotion.stress':6,
            'emotion.hope':4,'emotion.curiosity':5,
            'relation.ben.trust':3,'relation.ben.respect':4,
            'relation.ben.resentment':1,'relation.ben.debt':0,
            'priority.duty':9,'priority.family':8,'priority.safety':7}
    npc['social_state']={'values':values,
        'value_sources':{key:{'revision':0,'source':'initial encounter and role'} for key in values},
        'knowledge':{
            'player_has_pass':{'known':False,'text':'','revision':0,'source':'no pass shown'},
            'shift_time':{'known':True,'text':'天亮後交班。','revision':0,'source':'guard schedule'}},
        'boundaries':{'no_touch_weapon':True},
        'boundary_sources':{'no_touch_weapon':{'revision':0,'source':'established boundary'}}}
    def factor(id,direction,mandatory=True,weight=1):
        return {'id':id,'direction':direction,'weight':weight,'mandatory':mandatory}
    state['world']['social_contracts']={
        'gate_entry':{'npc_id':'hark','label':'請守衛准許進入城門',
            'base_dc':10,'factors':[factor('relation.ben.trust','support'),
                factor('priority.duty','resist'),factor('emotion.stress','resist'),
                factor('emotion.anger','resist')],
            'gate':{'kind':'knowledge','id':'player_has_pass','expected':True},
            'effect':{'kind':'permission','key':'gate_entry'},
            'responses':{'blocked':'哈克未見到有效通行證，仍須守住城門。',
                         'refused':'哈克核對後仍不願放行。',
                         'succeeded':'哈克核對後示意你可以進城。'},
            'source_revision':0,'source':'guard duty and gate rule'},
        'shift_question':{'npc_id':'hark','label':'詢問守衛交班時間',
            'base_dc':10,'factors':[factor('relation.ben.trust','support'),
                factor('emotion.stress','resist'),factor('emotion.curiosity','support',False)],
            'gate':{'kind':'knowledge','id':'shift_time','expected':True},
            'effect':{'kind':'share_fact','key':'shift_time'},
            'responses':{'blocked':'哈克沒有可靠的交班時間可提供。',
                         'refused':'哈克暫時不願透露交班時間。',
                         'succeeded':'哈克回答了你的問題。'},
            'source_revision':0,'source':'guard schedule'},
        'borrow_weapon':{'npc_id':'hark','label':'向守衛借用佩刀',
            'base_dc':15,'factors':[factor('relation.ben.trust','support'),
                factor('emotion.fear','resist')],
            'gate':{'kind':'boundary','id':'no_touch_weapon','expected':False},
            'effect':{'kind':'permission','key':'borrow_weapon'},
            'responses':{'blocked':'哈克不願讓陌生人碰他的佩刀。',
                         'refused':'哈克仍不肯借出佩刀。',
                         'succeeded':'哈克同意借出佩刀。'},
            'source_revision':0,'source':'established weapon boundary'}}
    return state


class SocialValueTests(unittest.TestCase):
    def test_hard_gate_blocks_even_high_trust_and_omitted_duty(self):
        state=fixture();state['npcs']['hark']['social_state']['values']['relation.ben.trust']=10
        rolled=[]
        result=resolve_social(state,'hark',{'contract_id':'gate_entry',
            'selected_factor_ids':['relation.ben.trust']},
            roller=lambda sides:rolled.append(sides) or 20)
        self.assertEqual(result['status'],'blocked')
        self.assertEqual(result['changes'],{})
        self.assertEqual(rolled,[])

    def test_verified_pass_uses_mandatory_duty_even_if_ai_omits_it(self):
        state=fixture();state['npcs']['hark']['social_state']['knowledge']['player_has_pass']={
            'known':True,'text':'班已出示有效通行證。','revision':1,'source':'verified pass event'}
        before=copy.deepcopy(state)
        result=resolve_social(state,'hark',{'contract_id':'gate_entry',
            'selected_factor_ids':['relation.ben.trust']},roller=lambda sides:15)
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual([row['id'] for row in result['factors']],
                         ['relation.ben.trust','priority.duty','emotion.stress','emotion.anger'])
        self.assertEqual(result['rolls'][0]['target'],14)
        self.assertTrue(result['changes']['world']['permissions']['gate_entry']['granted'])
        self.assertEqual(state,before)

    def test_high_anger_counts_even_if_ai_omits_it(self):
        state=fixture();social=state['npcs']['hark']['social_state']
        social['knowledge']['player_has_pass']={
            'known':True,'text':'班已出示有效通行證。','revision':1,'source':'verified pass event'}
        social['values']['emotion.anger']=9
        result=resolve_social(state,'hark',{'contract_id':'gate_entry',
            'selected_factor_ids':['relation.ben.trust']},roller=lambda sides:15)
        self.assertEqual(result['status'],'refused')
        self.assertEqual(result['rolls'][0]['target'],21)
        self.assertIn('emotion.anger',[row['id'] for row in result['factors']])

    def test_known_answer_can_be_shared_but_unknown_answer_cannot(self):
        state=fixture();choice={'contract_id':'shift_question','selected_factor_ids':[]}
        result=resolve_social(state,'hark',choice,roller=lambda sides:15)
        self.assertEqual(result['status'],'succeeded')
        state['npcs']['hark']['social_state']['knowledge']['shift_time']['known']=False
        blocked=resolve_social(state,'hark',choice,roller=lambda sides:self.fail('must not roll'))
        self.assertEqual(blocked['status'],'blocked')

    def test_personal_boundary_blocks_borrowing_even_on_high_roll(self):
        state=fixture();choice={'contract_id':'borrow_weapon',
                                 'selected_factor_ids':['relation.ben.trust']}
        result=resolve_social(state,'hark',choice,roller=lambda sides:self.fail('must not roll'))
        self.assertEqual(result['status'],'blocked')

    def test_new_social_contract_is_data_only_and_world_scoped(self):
        state=fixture()
        definition={'npc_id':'hark','label':'提議一起經營酒館','base_dc':14,
            'factors':[{'id':'relation.ben.trust','direction':'support','weight':1,'mandatory':True},
                       {'id':'emotion.curiosity','direction':'support','weight':1,'mandatory':True}],
            'gate':None,'effect':{'kind':'agreement','key':'open_tavern'},
            'responses':{'blocked':'哈克目前不能考慮這件事。',
                         'refused':'哈克婉拒了合作提議。',
                         'succeeded':'哈克同意和你共同籌備酒館。'},
            'source_revision':0,'source':'newly established partnership opportunity'}
        changed=register_social_contract(state,'tavern_partnership',definition)
        self.assertNotIn('tavern_partnership',state['world']['social_contracts'])
        result=resolve_social(changed,'hark',{'contract_id':'tavern_partnership',
            'selected_factor_ids':['relation.ben.trust','emotion.curiosity']},roller=lambda sides:15)
        self.assertEqual(result['status'],'succeeded')
        self.assertTrue(result['changes']['world']['social_agreements']['open_tavern']['agreed'])
        with self.assertRaises(RuleError):register_social_contract(changed,'tavern_partnership',definition)
        invalid={**definition,'effect':{'kind':'execute_python','key':'anything'}}
        with self.assertRaises(RuleError):register_social_contract(state,'unsafe_rule',invalid)

    def test_confirmed_event_updates_emotion_and_next_dc_with_provenance(self):
        state=fixture();state['npcs']['hark']['social_state']['knowledge']['player_has_pass']={
            'known':True,'text':'班已出示有效通行證。','revision':0,'source':'verified pass event'}
        choice={'contract_id':'gate_entry','selected_factor_ids':[]}
        before=resolve_social(state,'hark',choice,roller=lambda sides:14)
        updated=apply_social_event(state,'hark','angry_after_insult','confirmed insult event',
                                   deltas={'emotion.anger':3})
        after=resolve_social(updated,'hark',choice,roller=lambda sides:14)
        self.assertEqual(before['status'],'succeeded')
        self.assertEqual(after['status'],'refused')
        self.assertEqual((before['rolls'][0]['target'],after['rolls'][0]['target']),(14,17))
        self.assertEqual(updated['npcs']['hark']['social_state']['value_sources']['emotion.anger']['revision'],1)
        self.assertEqual(state['npcs']['hark']['social_state']['values']['emotion.anger'],2)
        with self.assertRaises(RuleError):
            apply_social_event(updated,'hark','angry_after_insult','same event',
                               deltas={'emotion.anger':1})
        with self.assertRaises(RuleError):
            apply_social_event(state,'hark','too_large_change','event',
                               deltas={'emotion.anger':8})

    def test_social_permission_persists_once_in_disposable_sqlite(self):
        state=fixture();state['npcs']['hark']['social_state']['knowledge']['player_has_pass']={
            'known':True,'text':'班已出示有效通行證。','revision':0,'source':'verified pass event'}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=state)
            decision=resolve_social(engine.state(),'hark',{
                'contract_id':'gate_entry','selected_factor_ids':[]},roller=lambda sides:15)
            reply={'narration':render_social(state,'請放行',decision),'changes':decision['changes']}
            first=engine.record_gm_reply('請放行',reply,'social-pass',0)
            second=engine.record_gm_reply('請放行',reply,'social-pass',0)
            self.assertEqual(first,second)
            self.assertEqual(engine.state()['revision'],1)
            self.assertTrue(engine.state()['world']['permissions']['gate_entry']['granted'])
            self.assertTrue(engine.verify())

    def test_confirmed_value_event_persists_with_source_in_disposable_sqlite(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=fixture())
            updated=apply_social_event(engine.state(),'hark','insult_seen','confirmed public insult',
                                       deltas={'emotion.anger':2})
            changes={'npcs':{'hark':{'social_state':updated['npcs']['hark']['social_state']}},
                     'world':{'social_value_events':updated['world']['social_value_events']}}
            engine.record_gm_reply('已確認的侮辱事件',{'narration':'哈克聽見侮辱，神情轉冷。',
                'changes':changes},'insult-event',0)
            saved=engine.state()
            self.assertEqual(saved['npcs']['hark']['social_state']['values']['emotion.anger'],4)
            self.assertEqual(saved['world']['social_value_events']['insult_seen']['source'],
                             'confirmed public insult')
            self.assertTrue(engine.verify())

    def test_invalid_value_or_cross_npc_rule_is_rejected(self):
        state=fixture();state['npcs']['hark']['social_state']['values']['emotion.anger']=11
        with self.assertRaises(RuleError):validate_social(state)
        state=fixture()
        with self.assertRaises(RuleError):resolve_social(state,'other',{
            'contract_id':'gate_entry','selected_factor_ids':[]},roller=lambda _:20)

    @patch('kobold_rpg.social_values_trial.count',return_value=None)
    @patch('kobold_rpg.social_values_trial.budget',return_value=None)
    def test_ai_selects_only_existing_factors(self,*_):
        state=fixture();messages=[]
        def fake(prompt,*_args,**_kwargs):
            messages.append(prompt)
            return json.dumps({'contract_id':'gate_entry',
                               'selected_factor_ids':['relation.ben.trust']})
        selected,_=select_social_context(state,'hark','請放我入城','http://none',fake)
        self.assertEqual(selected['contract_id'],'gate_entry')
        self.assertIn('priority.duty',messages[0][0]['content'])
        self.assertNotIn('priority.family',messages[0][0]['content'])
        with self.assertRaises(RuleError):
            select_social_context(state,'hark','請放我入城','http://none',
                lambda *_a,**_k:json.dumps({'contract_id':'gate_entry',
                                              'selected_factor_ids':['invented.goodwill']}))

    @patch('kobold_rpg.structured_state_trial.count',return_value=None)
    @patch('kobold_rpg.structured_state_trial.budget',return_value=None)
    @patch('kobold_rpg.social_values_trial.count',return_value=None)
    @patch('kobold_rpg.social_values_trial.budget',return_value=None)
    def test_social_turn_uses_two_model_calls_but_host_blocks_unverified_pass(self,*_):
        state=fixture();calls=[]
        parsed={'mode':'play','steps':[action('persuade','hark',utterance='請讓我進城')]}
        choice={'contract_id':'gate_entry','selected_factor_ids':['relation.ben.trust']}
        def complete(*_args,**_kwargs):
            calls.append(1)
            return json.dumps(parsed if len(calls)==1 else choice,ensure_ascii=False)
        result=trial_social_turn(state,'我請守衛讓我進城','http://none',complete,
                                 roller=lambda sides:self.fail('blocked means no roll'))
        self.assertEqual(len(calls),2)
        self.assertEqual(result['decision']['status'],'blocked')
        self.assertIn('未見到有效通行證',result['narration'])


if __name__=='__main__':unittest.main()
