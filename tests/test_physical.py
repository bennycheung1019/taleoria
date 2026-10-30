import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from kobold_rpg.engine import Engine,RuleError,normalize_action,validate_proposal,check_action
from kobold_rpg.campaign import new_campaign
from kobold_rpg.canon import digest
from kobold_rpg.physical import weapons
from kobold_rpg.model import react,enrich_characters


class PhysicalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.engine=Engine(Path(self.tmp.name)/'world.db',seed=new_campaign())
        self.action=normalize_action({'kind':'use_item','text':'我使用獵刀，stab Hark 10 times in the chest','target':'hark','item':'hunting_knife'})

    def proposal(self,fatal=False):
        return {'outcome':'partial','reason':'近身刺擊造成刀傷，未把連刺宣告當成多次命中。',
                'narration':'哈克胸前受傷，退後拉開距離。' if not fatal else '哈克受了致命刀傷，已死亡。',
                'events':[{'type':'harm','actor':'ben','target':'hark','weapon':'hunting_knife',
                           'condition':'胸前刀傷，出血' if not fatal else '受致命刀傷，已死亡','fatal':fatal,'basis':'已持有的獵刀在這次已裁定命中的交手中造成物理傷勢。'}]}

    def approve(self,proposal):
        state=self.engine.state();audit={'revision':state['revision'],'proposal_hash':digest(proposal),
            'result':{'supported':True,'actors':['ben','hark'],'powers':[],'issues':[]}}
        draft=self.engine.propose(self.action,proposal,state['revision'],audit=audit)
        return self.engine.approve(draft['id'],'accept',defer_people=True)

    def test_ordinary_knife_attempt_needs_no_combat_skill_or_supernatural_power(self):
        state=self.engine.state();state['pc']['capabilities']=[]
        self.assertEqual(check_action(state,self.action)[0],'review')
        validate_proposal(state,self.action,self.proposal())
        self.assertEqual(state['canon']['powers'],{})

    def test_injury_is_qualitative_persistent_and_does_not_rewrite_identity(self):
        before=self.engine.state();self.approve(self.proposal());state=self.engine.state()
        self.assertTrue(state['npcs']['hark']['alive']);self.assertIn('胸前刀傷，出血',state['npcs']['hark']['conditions'])
        self.assertEqual(state['canon'],before['canon']);self.assertNotIn('hp',state['npcs']['hark'])
        self.assertTrue(Engine(self.engine.path).verify())
        view=self.engine.public_state();self.assertIn('刀傷',view['locations']['gate']['description'])
        self.assertNotIn('正在門燈下查看交班紙',view['locations']['gate']['description'])

    def test_lethal_outcome_records_death_without_a_spell_or_automatic_resurrection(self):
        self.approve(self.proposal(True));state=self.engine.state()
        self.assertFalse(state['npcs']['hark']['alive']);self.assertEqual(state['canon']['powers'],{})
        self.assertEqual(check_action(state,normalize_action({'kind':'speak','target':'hark','text':'你還好嗎？'}))[0],'blocked')
        self.assertIn('已死亡',self.engine.public_state()['people']['hark']['observed_condition'])

    def test_npc_can_counter_with_previously_described_sword_and_player_can_die(self):
        self.assertIn('short_sword',weapons(self.engine.state(),'hark'))
        proposal={'outcome':'failure','reason':'刺擊被擋下，對手反擊。','narration':'哈克反擊造成致命傷，班已死亡。',
            'events':[{'type':'harm','actor':'hark','target':'ben','weapon':'short_sword','condition':'受致命傷，已死亡','fatal':True,'basis':'本次已成立的近身反擊。'}]}
        self.approve(proposal);state=self.engine.state();self.assertFalse(state['pc']['alive'])
        self.assertEqual(check_action(state,normalize_action({'kind':'observe','text':'環顧四周'}))[0],'blocked')

    def test_harm_requires_existing_item_target_presence_and_declared_attack(self):
        state=self.engine.state()
        for changes in [{'weapon':'magic_sword'},{'target':'anya'},{'fatal':'yes'}]:
            proposal=self.proposal();proposal['events'][0].update(changes)
            with self.assertRaises(RuleError):validate_proposal(state,self.action,proposal)
        with self.assertRaises(RuleError):validate_proposal(state,normalize_action({'kind':'speak','target':'hark','text':'你好。'}),self.proposal())

    def test_friendly_npc_cannot_harm_player_for_an_information_question(self):
        proposal=self.proposal();proposal['events'][0].update(actor='hark',target='ben',weapon='short_sword')
        with self.assertRaises(RuleError):validate_proposal(self.engine.state(),normalize_action({'kind':'speak','target':'hark','text':'今晚下雨嗎？'}),proposal)

    def test_negative_equipment_description_does_not_grant_a_sword(self):
        state=self.engine.state();state['npcs']['hark']['description']='哈克沒有佩普通短劍，雙手空著。'
        self.assertNotIn('short_sword',weapons(state,'hark'))

    def test_ten_declared_strikes_are_not_ten_automatic_damage_events(self):
        proposal=self.proposal();proposal['events']*=10
        with self.assertRaises(RuleError):validate_proposal(self.engine.state(),self.action,proposal)

    def test_uploaded_contradiction_is_rejected_before_writing(self):
        proposal={'outcome':'failure','reason':'班的宣告不在已登記能力範圍內；獵刀無法造成致命傷害。',
            'narration':'班刺向哈克，但哈克並未受傷。','events':[{'type':'npc_update','npc':'hark','field':'condition','value':'受傷，但未死亡'}]}
        before=self.engine.state()
        with self.assertRaisesRegex(RuleError,'失敗|未受傷'):validate_proposal(before,self.action,proposal)
        self.assertEqual(self.engine.state(),before)

    def test_invalid_ordinary_ability_denial_is_corrected_once_without_forcing_success(self):
        bad={'outcome':'failure','reason':'班的宣告不在已登記能力範圍內；獵刀無法造成致命傷害。','narration':'哈克沒有受傷。','events':[]}
        valid={'outcome':'failure','reason':'哈克擋開了這次刺擊。','narration':'哈克側身擋開獵刀，退了一步。','events':[]}
        with patch('kobold_rpg.model._complete',side_effect=[bad,valid]) as model:
            result=react(self.engine.state(),self.action,'http://local')
        self.assertEqual(model.call_count,2);self.assertEqual(result['outcome'],'failure');self.assertEqual(self.engine.state()['revision'],0)

    def test_legacy_item_injury_is_mapped_without_inventing_an_extra_hit(self):
        proposal=self.proposal();proposal['events']=[{'type':'npc_update','npc':'hark','field':'condition','value':'胸前受刀傷，出血'}]
        with patch('kobold_rpg.model._complete',return_value=proposal):result=react(self.engine.state(),self.action,'http://local')
        self.assertEqual(len(result['events']),1);self.assertEqual(result['events'][0]['type'],'harm');self.assertFalse(result['events'][0]['fatal'])

    def test_severe_injury_is_mapped_but_fear_of_injury_is_not(self):
        for condition,harm in [('重傷倒地',True),('胸部多處刺傷',True),('害怕受傷，保持距離',False),('並未受傷',False)]:
            proposal=self.proposal();proposal['events']=[{'type':'npc_update','npc':'hark','field':'condition','value':condition}]
            with patch('kobold_rpg.model._complete',return_value=proposal):result=react(self.engine.state(),self.action,'http://local')
            self.assertEqual(result['events'][0]['type']=='harm',harm)

    def test_preparation_only_narration_cannot_secretly_record_multiple_hits(self):
        proposal={'outcome':'failure','reason':'防禦使連刺失敗。','narration':'班將獵刀指向哈克的胸膛，準備連刺十次。',
                  'events':[{'type':'npc_update','npc':'hark','field':'condition','value':'胸部多處刺傷，血流不止'}]}
        with self.assertRaises(RuleError):validate_proposal(self.engine.state(),self.action,proposal)

    def test_wound_written_in_stance_still_becomes_a_real_injury(self):
        proposal=self.proposal();proposal['events']=[{'type':'npc_update','npc':'hark','field':'stance','value':'重傷倒地，無法進行防禦或反擊'}]
        with patch('kobold_rpg.model._complete',return_value=proposal):result=react(self.engine.state(),self.action,'http://local')
        self.assertEqual(result['events'][0]['type'],'harm')
        bad={**proposal,'outcome':'failure'}
        with self.assertRaises(RuleError):validate_proposal(self.engine.state(),self.action,bad)

    def test_flat_background_reflection_has_no_generated_actor_ids_or_fake_recalls(self):
        result={'emotions':['受到體諒而感激'],'interpretation':'感到對方願意尊重工作。','changes':{'respect':'願意繼續簡短交談'}}
        action=normalize_action({'kind':'speak','target':'hark','text':'謝謝你，辛苦了。'})
        with patch('kobold_rpg.model._complete',return_value=result):events=enrich_characters(self.engine.state(),action,'哈克說：「謝謝你的體諒。」','http://local')
        social=next(e for e in events if e['type']=='social_experience')
        self.assertEqual(social['npc'],'hark');self.assertEqual(social['subject'],'ben');self.assertEqual(social['recalls'],[])
        self.assertIsNone(social['changes']['respect']['before'])
        validate_proposal(self.engine.state(),action,{'outcome':'success','reason':'依據本次已感知的互動。','narration':'哈克說：「謝謝你的體諒。」','events':events})

    def test_numeric_relationship_scores_are_ignored_without_losing_valid_emotions(self):
        result={'emotions':['驚恐','憤怒'],'interpretation':'認為突然遭到攻擊，自己的安全受到威脅。',
                'changes':{'trust':0,'respect':0,'boundaries':'要求對方立即遠離，保護自身安全'}}
        before=self.engine.state()
        with patch('kobold_rpg.model._complete',return_value=result):events=enrich_characters(before,self.action,'哈克受傷倒地。','http://local')
        event=events[0]
        self.assertEqual(event['emotions'],['驚恐','憤怒'])
        self.assertEqual(set(event['changes']),{'boundaries'})
        self.assertEqual(self.engine.state(),before)
        validate_proposal(before,self.action,{'outcome':'success','reason':'只整理已發生的經歷。','narration':'哈克受傷倒地。','events':events})


if __name__=='__main__':unittest.main()
