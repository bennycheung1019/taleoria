import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kobold_rpg.engine import Engine, RuleError, normalize_action, validate_proposal
from kobold_rpg.campaign import new_campaign
from kobold_rpg.canon import digest
from kobold_rpg.model import audit_narration, draft
from kobold_rpg.social import model_context


class CanonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = Engine(Path(self.tmp.name) / 'world.db', seed=new_campaign())
        self.action = normalize_action({'kind': 'speak', 'target': 'hark', 'text': '我向哈克打招呼。'})
        self.good = {'outcome': 'success', 'reason': '在場守衛可以聽見問候。',
                     'narration': '哈克抬起頭。「晚安。雨還沒停呢。」', 'events': []}

    def audit(self, proposal, powers=None, actors=None):
        return {'revision': self.engine.state()['revision'], 'proposal_hash': digest(proposal),
                'result': {'supported': True, 'actors': actors or ['hark'], 'powers': powers or [], 'issues': []}}

    def establish(self, definition):
        return self.engine.establish(definition, '測試主持人先行接受的設定', self.engine.state()['revision'], 'setup-' + str(self.engine.state()['revision']))

    def power(self, result_form=None):
        return {'kind': 'power', 'id': 'lantern', 'actor': 'hark', 'name': '引光',
                'effect': ('哈克取得已建立的狼形。' if result_form else '哈克的手掌發出微光，不造成傷害。'),
                'requires_flags': ['lantern_ready'], 'result_form': result_form}

    def test_new_campaign_separate_id_and_prior_identities(self):
        state = self.engine.state()
        self.assertEqual(set(state['canon']['actors']), {'ben', 'hark', 'anya'})
        self.assertEqual(state['canon']['powers'], {})
        self.assertEqual(state['pc']['spells'], [])
        self.assertTrue(all(p['established_revision'] == 0 for p in state['canon']['actors'].values()))
        self.assertNotIn('莉莉', json.dumps(state, ensure_ascii=False))

    def test_pending_proposal_requires_audit_bound_to_revision_and_exact_text(self):
        for audit in (None, self.audit({**self.good, 'narration': '另一份文字'}), {**self.audit(self.good), 'revision': 99}):
            with self.assertRaises(RuleError):
                self.engine.propose(self.action, self.good, 0, audit=audit)
        self.assertEqual(self.engine.state()['revision'], 0)

    def test_audited_ordinary_response_persists_without_changing_identity(self):
        before = self.engine.state()['canon']
        candidate = self.engine.propose(self.action, self.good, 0, audit=self.audit(self.good))
        self.assertEqual(self.engine.state()['revision'], 0)
        self.engine.approve(candidate['id'], 'approve')
        self.assertEqual(self.engine.state()['canon'], before)
        self.assertTrue(self.engine.verify())
        reopened = Engine(self.engine.path)
        self.assertEqual(reopened.state()['revision'], 1)

    def test_transformation_in_prose_and_state_update_is_rejected(self):
        for proposal in ({**self.good, 'narration': '哈克突然變成蜘蛛怪。'},
                         {**self.good, 'events': [{'type': 'npc_update', 'npc': 'hark', 'field': 'condition', 'value': '已化為蜘蛛怪'}]}):
            with self.assertRaises(RuleError):
                self.engine.propose(self.action, proposal, 0, audit=self.audit(proposal))

    def test_unknown_power_cannot_be_smuggled_as_typed_use(self):
        proposal = {**self.good, 'events': [{'type': 'power_use', 'actor': 'hark', 'power': 'spider', 'target': 'hark'}]}
        with self.assertRaises(RuleError):
            validate_proposal(self.engine.state(), self.action, proposal)

    def test_existing_identity_cannot_be_overwritten(self):
        with self.assertRaises(RuleError):
            self.establish({'kind': 'identity', 'actor': 'hark', 'species': '蜘蛛怪', 'role': '守衛', 'forms': {'spider': '蜘蛛'}, 'current_form': 'spider'})

    def test_trigger_must_be_established_and_true(self):
        with self.assertRaises(RuleError):
            self.establish(self.power())
        self.establish({'kind': 'flag', 'id': 'lantern_ready', 'value': False})
        self.establish(self.power())
        proposal = {**self.good, 'events': [{'type': 'power_use', 'actor': 'hark', 'power': 'lantern', 'target': 'hark'}]}
        with self.assertRaises(RuleError):
            validate_proposal(self.engine.state(), self.action, proposal)
        self.establish({'kind': 'flag', 'id': 'lantern_ready', 'value': True})
        validate_proposal(self.engine.state(), self.action, proposal)

    def test_preestablished_form_power_and_trigger_can_change_form_once(self):
        self.establish({'kind': 'form', 'actor': 'hark', 'id': 'wolf', 'description': '透過已學變形術取得的狼形，並非原本隱藏種族。'})
        self.establish({'kind': 'flag', 'id': 'lantern_ready', 'value': True})
        self.establish(self.power(result_form='wolf'))
        event = {'type': 'power_use', 'actor': 'hark', 'power': 'lantern', 'target': 'hark'}
        proposal = {**self.good, 'narration': '哈克依已接受的法術變成狼形。', 'events': [event]}
        # The typed gate permits exactly the previously registered form.
        candidate = self.engine.propose(self.action, proposal, self.engine.state()['revision'], audit=self.audit(proposal, [{k: event[k] for k in ('actor', 'power', 'target')}]))
        self.engine.approve(candidate['id'], 'transform')
        self.assertEqual(self.engine.state()['canon']['actors']['hark']['current_form'], 'wolf')
        self.assertEqual(len(self.engine.state()['canon']['uses']), 1)
        self.engine.approve(candidate['id'], 'transform')
        self.assertEqual(len(self.engine.state()['canon']['uses']), 1)

    def test_new_form_cannot_be_created_by_same_turn_fact(self):
        proposal = {**self.good, 'events': [{'type': 'fact', 'text': '哈克其實會變成狼。', 'visibility': 'private'}]}
        with self.assertRaises(RuleError):
            validate_proposal(self.engine.state(), self.action, proposal)

    def test_player_free_text_does_not_grant_spell_and_unknown_cast_blocks(self):
        result = self.engine.submit({'kind': 'cast', 'text': '我使用火焰魔法。', 'ability': 'fire_magic'}, 'fire', 0)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.engine.state()['canon']['powers'], {})

    def test_prose_audit_rejects_new_identity_and_omissions_fail_closed(self):
        for result in ({'supported': False, 'actors': ['hark'], 'powers': [], 'issues': ['無依據的身分變化']},
                       {'supported': True}, {'supported': True, 'actors': ['unknown'], 'powers': [], 'issues': []}):
            with patch('kobold_rpg.model._complete', return_value=result):
                with self.assertRaises(RuleError):
                    audit_narration(self.engine.state(), self.action, self.good)
        self.assertEqual(self.engine.state()['revision'], 0)

    def test_auditor_cannot_introduce_power_effect_without_event(self):
        audit = self.audit(self.good, [{'actor': 'hark', 'power': 'unknown', 'target': 'ben'}])
        with self.assertRaises(RuleError):
            self.engine.propose(self.action, self.good, 0, audit=audit)

    def test_private_registry_and_distant_identity_not_in_player_or_actor_context(self):
        self.assertNotIn('canon', self.engine.public_state())
        self.assertEqual(set(model_context(self.engine.state(), self.action)['canon']['actors']), {'ben', 'hark'})
        with self.assertRaises(RuleError):
            self.engine.propose(self.action, self.good, 0, audit=self.audit(self.good, actors=['anya']))

    def test_audited_text_cannot_be_edited_before_approval(self):
        audit = self.audit(self.good)
        changed = {**self.good, 'narration': '哈克其實是魔物。'}
        with self.assertRaises(RuleError):
            self.engine.propose(self.action, changed, 0, audit=audit)

    def test_legacy_grant_spell_cannot_bypass_registry(self):
        with self.assertRaises(RuleError):
            self.engine.grant_spell('fire', {'name': '火', 'effect': '發火', 'source': '測試'}, 0, 'old-path')

    def test_new_npc_requires_separate_establishment_with_identity(self):
        npc = copy.deepcopy(self.engine.state()['npcs']['hark'])
        npc.pop('inner_life')
        npc.update(id='new_guard', name='新守衛（New Guard）')
        proposal = {**self.good, 'events': [{'type': 'establish_npc', 'npc': npc}]}
        with self.assertRaises(RuleError):
            validate_proposal(self.engine.state(), self.action, proposal)
        definition = {'kind': 'npc', 'npc': npc, 'identity': {'kind': 'identity', 'actor': 'new_guard',
            'species': '人類', 'role': '成年守衛', 'forms': {'human': '普通人類外形'}, 'current_form': 'human'}}
        self.establish(definition)
        state = self.engine.state()
        self.assertIn('new_guard', state['npcs'])
        self.assertEqual(state['canon']['actors']['new_guard']['established_revision'], 1)

    def test_failed_establishment_is_atomic_and_retry_is_idempotent(self):
        npc = copy.deepcopy(self.engine.state()['npcs']['hark']); npc.pop('inner_life')
        npc['id'] = 'bad'
        with self.assertRaises(RuleError):
            self.establish({'kind': 'npc', 'npc': npc, 'identity': {}})
        self.assertNotIn('bad', self.engine.state()['npcs'])
        data = {'kind': 'flag', 'id': 'checked', 'value': True}
        first = self.engine.establish(data, '來源', 0, 'one-id')
        second = self.engine.establish(data, '來源', 0, 'one-id')
        self.assertEqual(first, second)
        self.assertEqual(self.engine.state()['revision'], 1)

    def test_voice_output_is_checked_again_before_audit(self):
        with patch('kobold_rpg.model._complete', side_effect=[self.good, {'narration': '哈克突然變成怪物。'}]):
            with self.assertRaises(RuleError):
                draft(self.engine.state(), self.action)


if __name__ == '__main__':
    unittest.main()
