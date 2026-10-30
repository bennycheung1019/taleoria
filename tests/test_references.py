import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from kobold_rpg.campaign import new_campaign
from kobold_rpg.canon import digest
from kobold_rpg.engine import Engine, RuleError, validate_proposal, normalize_action
from kobold_rpg.model import audit_narration, react
from kobold_rpg.play import interpret
from kobold_rpg.references import referenced_characters, audit_actor_ids
from kobold_rpg.social import model_context


class CharacterReferenceTests(unittest.TestCase):
    def setUp(self):
        self.state = new_campaign()
        self.state['pc']['location'] = 'river_street'
        self.action = normalize_action({'kind':'freeform','text':'I look toward Anya from the river street.'})
        self.proposal = {'outcome':'success', 'reason':'只依河街上已提供的遠處景象觀察。',
                         'narration':'你望向渡口。安雅（Anya）仍在整理繫船索；這裡看不清更多細節。', 'events':[]}

    def test_original_inspection_is_an_action_and_does_not_select_a_distant_physical_target(self):
        action = interpret(self.state, 'check out Anya', resolver=Mock(side_effect=AssertionError('no parser needed')))
        self.assertEqual(action['understanding']['mode'], 'action')
        self.assertEqual(action['text'], 'check out Anya')
        self.assertEqual(action['kind'], 'observe')
        self.assertEqual(action['target'], 'anya')

    def test_simple_inspection_only_delivers_existing_evidence_without_new_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(Path(directory)/'observe.sqlite3', seed=self.state)
            before=engine.state()
            action=interpret(before,'check out Anya')
            result=engine.submit(action,'simple-inspection',0)
            self.assertEqual(result['status'],'routine')
            self.assertIn('安雅正在整理繫船索',result['narration'])
            for invented in ('帽子','手套','外套','未察覺'):
                self.assertNotIn(invented,result['narration'])
            after=engine.state();after['revision']=before['revision']
            self.assertEqual(after,before)
            self.assertEqual(engine.history()[-1]['events'],[])
            self.assertTrue(engine.verify())

    def test_name_in_an_extra_action_or_dialogue_never_uses_the_inspection_shortcut(self):
        from kobold_rpg.references import inspection_target
        for value in ('check out Anya then stab her','check out Anya and take her boat','check out Anyam'):
            self.assertIsNone(inspection_target(self.state,value))
        quoted=interpret(self.state,'"check out Anya"')
        self.assertEqual(quoted['kind'],'speak')

    def test_scene_reference_is_available_without_private_or_close_range_information(self):
        context = model_context(self.state, self.action)
        reference = context['referenced_characters']['anya']
        self.assertEqual(reference['access'], 'reference_only')
        self.assertIn('安雅', ''.join(reference['current_scene_mentions']))
        self.assertNotIn('anya', context['npcs'])
        self.assertNotIn('anya', context['canon']['actors'])
        for secret in ('inner_life','anchor','conditions','厚外套','船主'):
            self.assertNotIn(secret, json.dumps(reference, ensure_ascii=False))
        self.assertEqual(audit_actor_ids(self.state, self.action), ['anya','ben'])

    def test_reference_audit_has_exact_id_constraints_in_one_existing_call(self):
        verdict = {'supported':True,'actors':['ben','anya'],'powers':[],'issues':[]}
        with patch('kobold_rpg.model._complete', return_value=verdict) as complete:
            audit = audit_narration(self.state, self.action, self.proposal)
        self.assertEqual(complete.call_count, 1)
        schema = complete.call_args.kwargs['response_schema']
        self.assertEqual(schema['properties']['actors']['items']['enum'], ['anya','ben'])
        context = json.loads(complete.call_args.args[0][-1]['content'])['established']
        self.assertEqual(context['referenced_characters']['anya']['access'], 'reference_only')
        self.assertEqual(audit['result'], verdict)

    def test_unknown_typo_is_never_fuzzily_mapped_to_an_existing_character(self):
        with patch('kobold_rpg.model._complete', return_value={'supported':True,'actors':['ben','anym'],'powers':[],'issues':[]}):
            with self.assertRaises(RuleError): audit_narration(self.state, self.action, self.proposal)

    def test_referenced_character_does_not_teleport_or_change_identity_when_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(Path(directory)/'world.sqlite3', seed=self.state)
            audit = {'revision':0,'proposal_hash':digest(self.proposal),
                     'result':{'supported':True,'actors':['ben','anya'],'powers':[],'issues':[]}}
            pending = engine.propose(self.action, self.proposal, 0, audit=audit)
            engine.approve(pending['id'], 'inspect-anya')
            after = engine.state()
            self.assertEqual(after['pc']['location'], 'river_street')
            self.assertEqual(after['npcs']['anya'], self.state['npcs']['anya'])
            self.assertEqual(after['canon'], self.state['canon'])
            self.assertTrue(engine.verify())

    def test_reference_cannot_receive_a_remote_stance_update_or_physical_harm(self):
        proposal = {**self.proposal,'events':[{'type':'npc_update','npc':'anya','field':'stance','value':'對玩家微笑'}]}
        with patch('kobold_rpg.model._complete', return_value=proposal):
            with self.assertRaises(RuleError): react(self.state, self.action)
        attack = interpret(self.state,'stab Anya with my knife')
        with self.assertRaises(RuleError): validate_proposal(self.state, attack, {**self.proposal,'events':[
            {'type':'harm','actor':'ben','target':'anya','weapon':'hunting_knife','condition':'受傷','fatal':False,'basis':'普通攻擊'}]})

    def test_unseen_and_unmentioned_people_stay_out_of_references(self):
        gate = new_campaign()
        self.assertNotIn('anya', referenced_characters(gate, interpret(gate,'say hello')))
        gate['npcs']['anya']['known'] = False
        self.assertNotIn('anya', referenced_characters(gate, self.action))
        self.assertNotIn('anya', audit_actor_ids(gate, self.action))

    def test_exact_name_boundaries_and_present_character_retrieval(self):
        state = new_campaign()
        for value in ('look at Anyam', 'check out manyAnya'):
            self.assertNotIn('anya', referenced_characters(state, {'text':value}))
        self.assertIn('anya', referenced_characters(state, {'text':'look at ANYA'}))
        state['pc']['location'] = 'pier'
        context = model_context(state, interpret(state,'check out Anya'))
        self.assertIn('anya', context['npcs'])
        self.assertNotIn('anya', context['referenced_characters'])


if __name__ == '__main__': unittest.main()
