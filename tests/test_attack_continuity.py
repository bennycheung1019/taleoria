"""Regressions from the actual three-turn neck-attack loop."""
import copy
import json
import unittest
from unittest.mock import patch
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import RuleError,normalize_action,validate_proposal
from kobold_rpg.play import interpret
from kobold_rpg.physical import attacking,ordinary_exchange,scene_text
from kobold_rpg.model import react


SETUP='班舉起獵刀，準備割下哈克的頸部，但哈克察覺到班的舉動，快速將交班紙收起，拔出短劍，指向班，說道：『你想做什麼？』'
WARNING='哈克見班舉起獵刀，馬上察覺到危險，將交班紙收起，拔出短劍，指向班，警告道：『你想做什麼？』'


class AttackContinuityTests(unittest.TestCase):
    def setUp(self):self.state=new_campaign()

    def test_actual_three_declarations_reach_the_ordinary_attack_path(self):
        for text in ["take out my knife and slice across Hark's neck",'aim for his neck and stab him','aim for his neck and stab him']:
            action=interpret(self.state,text)
            self.assertTrue(attacking(action));self.assertEqual(action['target'],'hark')
            self.assertTrue(ordinary_exchange(self.state,action))
            if 'knife' in text:self.assertEqual((action['kind'],action['item']),('use_item','hunting_knife'))

    def test_item_shortcut_does_not_skip_resolving_an_explicit_target_or_pronoun(self):
        for text in ['我使用獵刀刺向哈克。','aim for his neck and stab him']:
            action=interpret(self.state,text,{'kind':'use_item','item':'hunting_knife'})
            self.assertEqual(action['target'],'hark');self.assertEqual(action['item'],'hunting_knife')

    def test_multiple_people_are_not_silently_selected_by_a_pronoun(self):
        self.state['npcs']['anya']['location']='gate'
        action=interpret(self.state,'aim for his neck and stab him')
        self.assertEqual(action['target'],'')

    def test_no_weapon_is_invented_or_automatically_equipped_from_inventory(self):
        action=interpret(self.state,'aim for his neck and stab him')
        self.assertEqual(action['item'],'');self.assertEqual(action['kind'],'freeform')
        self.state['pc']['inventory']['hunting_knife']=0
        action=interpret(self.state,'use my knife to stab Hark')
        self.assertNotEqual(action.get('item'),'hunting_knife')

    def test_private_thought_and_dialogue_are_not_executed_as_attacks(self):
        for text in ['我心想要刺他。','我問哈克：「你會刺他嗎？」']:
            self.assertFalse(attacking(interpret(self.state,text)))
        from kobold_rpg.understanding import pack
        self.assertFalse(attacking(interpret(self.state,'I cut across the street',resolver=lambda text:pack('action',text))))

    def test_saved_setup_and_warning_are_not_resolved_attacks_even_without_an_item_field(self):
        action=interpret(self.state,'aim for his neck and stab him')
        for text,reason in [(SETUP,'哈克拔出短劍，防禦了班的攻擊，未受到傷害。'),(WARNING,'防衛反應，未發生實際攻擊')]:
            with self.assertRaises(RuleError):
                validate_proposal(self.state,action,{'outcome':'failure','reason':reason,'narration':text,'events':[]})

    def test_real_block_or_miss_is_valid_and_never_forced_to_be_a_hit(self):
        action=interpret(self.state,'aim for his neck and stab him')
        for text in ['哈克用短劍擋開刺向頸側的刀刃，這次刺擊落空。','哈克閃開，刀刃從頸側擦過，沒有造成傷口。']:
            result=validate_proposal(self.state,action,{'outcome':'failure','reason':'刀刃被擋開或避過，未命中。','narration':text,'events':[]})
            self.assertEqual(result['outcome'],'failure')

    def test_unapplied_warning_gets_one_repair_with_its_actual_problem(self):
        action=interpret(self.state,'aim for his neck and stab him')
        bad={'outcome':'partial','reason':'哈克防衛，未發生實際攻擊。','narration':WARNING,'events':[]}
        good={'outcome':'failure','reason':'哈克擋開了刺向頸側的刀刃。','narration':'班刺出獵刀，哈克用已出鞘的短劍擋開這次刺擊。','events':[]}
        with patch('kobold_rpg.model._complete',side_effect=[bad,good]) as model:
            result=react(self.state,action,'http://local',recent=[SETUP])
        self.assertEqual(result,good);self.assertEqual(model.call_count,2)
        prompt=json.loads(model.call_args.args[0][-1]['content'])
        self.assertIn('沒有呈現已宣告攻擊',prompt['correction_of_unapplied_draft'])
        self.assertEqual(self.state['revision'],0)

    def test_second_unresolved_reply_is_rejected_without_saving_or_rerolling_forever(self):
        action=interpret(self.state,'aim for his neck and stab him')
        bad={'outcome':'failure','reason':'只發出警告。','narration':WARNING,'events':[]}
        before=copy.deepcopy(self.state)
        with patch('kobold_rpg.model._complete',return_value=bad) as model:
            with self.assertRaises(RuleError):react(self.state,action,'http://local',recent=[SETUP])
        self.assertEqual(model.call_count,2);self.assertEqual(self.state,before)

    def test_current_combat_stance_overrides_the_old_scene_activity(self):
        self.state['npcs']['hark']['encounter']['stance']='警戒，持劍防衛'
        text=scene_text(self.state)
        self.assertNotIn('核對一張',text);self.assertIn('警戒，持劍防衛',text)
        action=interpret(self.state,'aim for his neck and stab him')
        reply={'outcome':'failure','reason':'擋開刀刃。','narration':'哈克擋開刀刃。','events':[]}
        with patch('kobold_rpg.model._complete',return_value=reply) as model:react(self.state,action,'http://local',recent=[SETUP])
        prompt=json.loads(model.call_args.args[0][-1]['content'])
        self.assertEqual(prompt['current_state']['target']['condition'],[])
        self.assertNotIn('核對一張',prompt['current_state']['scene']['description'])

    def test_untyped_injury_without_a_declared_item_must_be_corrected_not_silently_applied(self):
        action=interpret(self.state,'aim for his neck and stab him')
        with self.assertRaises(RuleError):
            validate_proposal(self.state,action,{'outcome':'partial','reason':'刀刃擦過頸側。','narration':'哈克頸側受傷。',
                'events':[{'type':'npc_update','npc':'hark','field':'condition','value':'頸側刺傷'}]})

    def test_a_ruled_hit_from_the_same_pronoun_action_can_be_saved(self):
        import tempfile
        from pathlib import Path
        from kobold_rpg.engine import Engine
        from kobold_rpg.canon import digest
        action=interpret(self.state,'aim for his neck and stab him')
        proposal={'outcome':'partial','reason':'刀刃擦中頸側，未造成致命傷。','narration':'獵刀擦過哈克頸側，留下割傷；哈克退開。',
            'events':[{'type':'harm','actor':'ben','target':'hark','weapon':'hunting_knife','condition':'頸側割傷','fatal':False,'basis':'本次刀刃擦中頸側。'}]}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'qa.sqlite3',seed=self.state)
            audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['ben','hark'],'powers':[],'issues':[]}}
            candidate=engine.propose(action,proposal,0,audit=audit)
            engine.approve(candidate['id'],'hit-once')
            self.assertIn('頸側割傷',engine.state()['npcs']['hark']['conditions'])
            self.assertTrue(engine.state()['npcs']['hark']['alive'])


if __name__=='__main__':unittest.main()
