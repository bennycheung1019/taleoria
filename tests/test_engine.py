import copy
import json
import tempfile
import unittest
from pathlib import Path

from kobold_rpg.engine import Engine, RuleError, check_action, normalize_action
from kobold_rpg.model import parse_proposal
from kobold_rpg.rulebook import excerpts


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.sqlite3"
        self.engine = Engine(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def action(self, kind="cast", **extras):
        return {"kind": kind, "text": "我嘗試施放火焰魔法。", "ability": "fire_magic", **extras}

    def proposal(self, **overrides):
        return {"outcome": "partial", "reason": "守衛需要可靠協助，但不願擅離職守。",
                "narration": "哈克問你能提供甚麼具體幫助，尚未答應你的請求。", "events": [], **overrides}

    def test_unlearned_spell_blocks_without_world_effects(self):
        before = self.engine.state()
        result = self.engine.submit(self.action(target="hark"), "spell", 0)
        self.assertEqual(result["status"], "blocked")
        after = self.engine.state()
        after["revision"] = 0
        self.assertEqual(after, before)
        self.assertTrue(self.engine.verify())

    def test_cannot_override_blocked_spell_with_model_proposal(self):
        with self.assertRaises(RuleError):
            self.engine.propose(self.action(), self.proposal(outcome="success"), 0, "koboldcpp")
        self.assertEqual(self.engine.state()["revision"], 0)

    def test_player_action_does_not_grant_ability(self):
        result = self.engine.submit(self.action("freeform", text="我覺醒火焰魔法並燒毀城門"), "attempt", 0)
        self.assertEqual(result["status"], "review")
        self.assertEqual(self.engine.state()["pc"]["spells"], [])
        self.assertEqual(self.engine.history(), [])

    def test_npc_request_requires_review_and_preserves_player(self):
        before = self.engine.state()
        action = self.action("interact", text="我要求哈克交出武器。", target="hark")
        self.assertEqual(self.engine.submit(action, "request", 0)["status"], "review")
        self.assertEqual(self.engine.state(), before)
        proposal = self.engine.propose(action, self.proposal(events=[
            {"type": "npc_update", "npc": "hark", "field": "stance", "value": "要求先說明用途，未同意交出武器"}
        ]), 0)
        self.assertEqual(self.engine.state(), before)
        self.engine.approve(proposal["id"], "approval")
        self.assertEqual(self.engine.state()["pc"], before["pc"])
        self.assertEqual(self.engine.state()["npcs"]["hark"]["encounter"]["stance"], "要求先說明用途，未同意交出武器")

    def test_model_cannot_write_arbitrary_state(self):
        for event in [{"type": "learn_spell", "ability": "fire_magic"},
                      {"type": "set", "path": "pc.alive", "value": False},
                      {"type": "npc_update", "npc": "hark", "field": "alive", "value": False}]:
            with self.assertRaises(RuleError):
                self.engine.propose(self.action("freeform"), self.proposal(events=[event]), 0)

    def test_model_cannot_move_player_without_declaration(self):
        with self.assertRaises(RuleError):
            self.engine.propose(self.action("speak"), self.proposal(events=[{"type": "move", "destination": "shelter"}]), 0)

    def test_known_spell_still_requires_resolution(self):
        self.engine.grant_spell("fire_magic", {"name": "小火苗", "effect": "只能點燃手中乾燥火絨，不可遠距攻擊", "source": "主持人接受的測試設定"}, 0, "learn")
        self.assertEqual(self.engine.submit(self.action(), "cast", 1)["status"], "review")
        self.assertEqual(self.engine.state()["revision"], 1)

    def test_cost_and_required_item_checked_without_guessing(self):
        state = self.engine.state()
        state["pc"]["spells"] = ["fire_magic"]
        state["abilities"]["fire_magic"] = {"source": "測試規則", "effect": "火苗", "cost": {"mana": 2}}
        action = normalize_action(self.action())
        self.assertEqual(check_action(state, action)[0], "clarify")
        state["pc"]["resources"]["mana"] = 1
        self.assertEqual(check_action(state, action)[0], "blocked")
        state["pc"]["resources"]["mana"] = 2
        state["abilities"]["fire_magic"]["requires"] = ["tinder"]
        self.assertEqual(check_action(state, action)[0], "blocked")
        state["pc"]["inventory"]["tinder"] = 1
        self.assertEqual(check_action(state, action)[0], "review")

    def test_no_fake_dice_or_automatic_stats(self):
        pc = self.engine.state()["pc"]
        self.assertEqual(pc["resources"], {})
        self.assertNotIn("hp", pc)
        self.assertNotIn("level", pc)

    def test_missing_items_and_remote_target(self):
        self.assertEqual(self.engine.submit(self.action("use_item", item="magic_wand"), "item", 0)["status"], "blocked")
        self.assertEqual(self.engine.submit(self.action("speak", target="imaginary"), "target", 1)["status"], "blocked")

    def test_routine_move_orientation_and_persistence(self):
        result = self.engine.submit(self.action("travel", destination="shelter"), "move", 0)
        self.assertEqual(result["status"], "routine")
        self.assertIn("木棚", result["narration"])
        reloaded = Engine(self.path)
        self.assertEqual(reloaded.state()["pc"]["location"], "shelter")

    def test_unknown_route_requires_clarification(self):
        result = self.engine.submit(self.action("travel", destination="castle"), "teleport", 0)
        self.assertEqual(result["status"], "clarify")
        self.assertEqual(self.engine.state()["pc"]["location"], "gate")

    def test_stale_proposal_rejected(self):
        p = self.engine.propose(self.action("speak"), self.proposal(), 0)
        self.engine.submit(self.action("observe"), "look", 0)
        with self.assertRaises(RuleError):
            self.engine.approve(p["id"], "late")

    def test_idempotent_action_and_approval(self):
        first = self.engine.submit(self.action(), "same", 0)
        second = self.engine.submit(self.action(), "same", 0)
        self.assertEqual(first, second)
        self.assertEqual(len(self.engine.history()), 1)
        with self.assertRaises(RuleError):
            self.engine.submit(self.action("observe"), "same", 0)
        p = self.engine.propose(self.action("speak"), self.proposal(), 1)
        self.assertEqual(self.engine.approve(p["id"], "approve"), self.engine.approve(p["id"], "approve"))
        with self.assertRaises(RuleError):
            self.engine.approve(p["id"], "different")

    def test_rewind_restores_state_and_preserves_history(self):
        self.engine.submit(self.action("travel", destination="shelter"), "move", 0)
        first = self.engine.rewind(0, 1, "rewind")
        self.assertEqual(first, self.engine.rewind(0, 1, "rewind"))
        self.assertEqual(self.engine.state()["pc"]["location"], "gate")
        self.assertEqual(self.engine.state()["revision"], 2)
        self.assertEqual(len(self.engine.history()), 2)
        self.assertTrue(self.engine.verify())

    def test_private_npc_facts_not_in_player_state(self):
        p = self.engine.propose(self.action("speak"), self.proposal(events=[
            {"type": "fact", "text": "哈克暗中擔心弟弟", "visibility": "private"}]), 0)
        self.engine.approve(p["id"], "private")
        self.assertEqual(self.engine.public_state()["facts"], [])
        self.assertNotIn("anchor", self.engine.public_state()["npcs"]["hark"])
        self.assertEqual(len(self.engine.state()["facts"]), 1)

    def test_permadeath_not_reset_by_maintenance(self):
        self.engine.maintain({"alive": False}, "已接受的致命後果", 0, "death")
        self.assertEqual(self.engine.submit(self.action("observe"), "afterdeath", 1)["status"], "blocked")
        with self.assertRaises(RuleError):
            self.engine.maintain({"alive": True}, "隨意復活", 2, "resurrection")

    def test_bad_model_json_does_not_change_state(self):
        before = self.engine.state()
        with self.assertRaises(RuleError):
            parse_proposal('我覺得你應該成功！')
        self.assertEqual(self.engine.state(), before)

    def test_unknown_events_and_clarify_with_effects_rejected(self):
        with self.assertRaises(RuleError):
            self.engine.propose(self.action("freeform"), self.proposal(outcome="clarify", events=[
                {"type": "fact", "text": "已成功", "visibility": "public"}]), 0)

    def test_head_tampering_detected(self):
        self.engine.submit(self.action(), "blocked", 0)
        with self.engine.connect() as db:
            state = self.engine.state()
            state["pc"]["spells"].append("illegal_magic")
            db.execute("UPDATE state SET body=?", (json.dumps(state),))
        with self.assertRaises(RuleError):
            self.engine.verify()

    def test_new_npc_needs_personal_anchor_and_five_fields(self):
        npc = copy.deepcopy(self.engine.state()["npcs"]["hark"])
        npc["id"] = "new_guard"
        del npc["anchor"]
        with self.assertRaises(RuleError):
            self.engine.propose(self.action("freeform"), self.proposal(events=[{"type": "establish_npc", "npc": npc}]), 0)

    def test_original_rule_sources_are_verified_and_retrieved(self):
        text = excerpts("interact")
        self.assertIn("SOURCE: ENGINE/freeform.md", text)
        self.assertIn("Social requests", text)
        self.assertIn("SOURCE: OS/AGENT_STATE.md", text)
        self.assertNotIn("SOURCE: ENGINE/freeform.md", excerpts("cast"))


if __name__ == "__main__":
    unittest.main()
