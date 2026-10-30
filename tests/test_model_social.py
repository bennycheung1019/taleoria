import copy
import json
import unittest
from unittest.mock import patch

from kobold_rpg.engine import RuleError, initial_state, normalize_action
from kobold_rpg.model import draft
from kobold_rpg.social import model_context


class ModelSocialTests(unittest.TestCase):
    def setUp(self):
        self.state = initial_state()
        self.action = normalize_action({"kind": "interact", "target": "hark", "text": "我謝謝哈克，也問他願不願意改天再聊。"})
        self.proposal = {"outcome": "partial", "reason": "被體諒而感激，仍須顧及交班。", "narration": "草案文字。",
                         "events": [{"type": "social_experience", "npc": "hark", "subject": "ben",
                                     "observed": "班道謝並邀請改天再聊，未要求現在離崗。",
                                     "interpretation": "覺得受到體諒，還需要考慮自己的安排。",
                                     "emotions": ["被理解而感到溫暖"], "changes": {}, "recalls": []}]}

    def test_person_voice_sees_proposed_feelings_without_committing(self):
        before = copy.deepcopy(self.state)
        with patch('kobold_rpg.model._complete', side_effect=[self.proposal, {"narration": "哈克笑了一下。「謝謝你這麼說。等我交班後再看看，好嗎？」"}]) as complete:
            result = draft(self.state, self.action)
        self.assertEqual(self.state, before)
        self.assertIn("謝謝", result["narration"])
        voice_input = json.loads(complete.call_args_list[1].args[0][1]["content"])
        self.assertEqual(voice_input["speaker"]["inner_life"]["current_emotions"][0]["feeling"], "被理解而感到溫暖")
        self.assertEqual(result["events"], self.proposal["events"])

    def test_voice_cannot_add_state_events(self):
        with patch('kobold_rpg.model._complete', side_effect=[self.proposal, {"narration": "新文字", "events": [{"type": "learn_spell"}]}]):
            with self.assertRaises(RuleError):
                draft(self.state, self.action)
        self.assertNotIn("inner_life", self.state["npcs"]["hark"])

    def test_optional_misquoted_character_note_is_not_saved_as_fact(self):
        proposal=copy.deepcopy(self.proposal)
        proposal['events'].append({'type':'character_note','npc':'hark','kind':'said','quote':'並不存在的逐字摘錄。'})
        with patch('kobold_rpg.model._complete',side_effect=[proposal,{'narration':'哈克點點頭：「謝謝你。」'}]):
            result=draft(self.state,self.action)
        self.assertFalse(any(e['type']=='character_note' for e in result['events']))
        self.assertEqual(result['events'][0]['type'],'social_experience')

    def test_targeted_context_does_not_mix_other_people_private_motives(self):
        other = copy.deepcopy(self.state["npcs"]["hark"])
        other["id"], other["name"] = "mira", "米拉（Mira）"
        other["anchor"]["concern"] = "米拉自己的私人顧慮"
        self.state["npcs"]["mira"] = other
        action = normalize_action({"kind": "interact", "target": "mira", "text": "我只邀請米拉。"})
        context = model_context(self.state, action)
        self.assertEqual(set(context["npcs"]), {"mira"})
        self.assertNotIn("anchor", context["other_present"][0])
        wrong = {"outcome": "failure", "reason": "測試人物混線", "narration": "哈克回答。", "events": [
            {"type": "npc_update", "npc": "hark", "field": "stance", "value": "錯誤地替另一位人物回答"}]}
        with patch('kobold_rpg.model._complete', return_value=wrong) as complete:
            with self.assertRaises(RuleError):
                draft(self.state, action)
            self.assertEqual(complete.call_count, 1)

    def test_rules_include_original_emotional_and_change_guidance(self):
        from kobold_rpg.rulebook import excerpts
        source = excerpts('interact')
        self.assertIn('Allow affection, pride, pleasure and hope', source)
        self.assertIn('Attraction, trust, cooperation, commitment', source)


if __name__ == '__main__':
    unittest.main()
