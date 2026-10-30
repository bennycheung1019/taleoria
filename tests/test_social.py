import copy
import tempfile
import unittest
from pathlib import Path

from kobold_rpg.engine import Engine, RuleError
from kobold_rpg.social import inner_life, model_context


class SocialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "world.sqlite3"
        self.engine = Engine(self.path)
        self.counter = 0

    def tearDown(self):
        self.tmp.cleanup()

    def action(self):
        return {"kind": "speak", "target": "hark", "text": "我謝謝哈克在雨中守門，問他是否需要我傳話給交班的人。"}

    def profile(self, npc="hark", limits=None):
        return {"type": "npc_personality", "npc": npc,
                "description": "容易對體貼他人的行為感到溫暖，但害怕承諾做不到的事；責任感與感情可能衝突。",
                "basis": "新建立的前瞻性細節；不宣稱是之前拒絕的既定原因。", "limits": limits or []}

    def experience(self, npc="hark", subject="ben", changes=None, recalls=None):
        return {"type": "social_experience", "npc": npc, "subject": subject,
                "observed": "班道謝並詢問是否需要替守衛傳話，沒有要求他立刻離崗。",
                "interpretation": "他認為自己的辛勞被注意到，但還不知道班是否會履行幫忙。",
                "emotions": ["受到體諒的溫暖", "仍擔心交班延誤"],
                "changes": changes if changes is not None else {"trust": {"before": None, "after": "比先前更願意聽班說話，仍待觀察是否可靠"}},
                "recalls": recalls or []}

    def accept(self, events):
        self.counter += 1
        proposal = {"outcome": "partial", "reason": "個人性格、被體諒的感受與守門顧慮同時影響反應。",
                    "narration": "哈克的肩膀稍微放鬆。「謝謝。你若遇見交班的人，請替我催一聲。」", "events": events}
        p = self.engine.propose(self.action(), proposal, self.engine.state()["revision"])
        return p, self.engine.approve(p["id"], f"accepted-{self.counter}")

    def test_feelings_wait_for_acceptance_and_survive_restart(self):
        before = self.engine.state()
        proposal = {"outcome": "partial", "reason": "因被體諒而感激，但沒有消除責任。", "narration": "哈克輕聲道謝。",
                    "events": [self.profile(), self.experience()]}
        p = self.engine.propose(self.action(), proposal, 0)
        self.assertEqual(before, self.engine.state())
        self.engine.approve(p["id"], "emotion")
        reloaded = Engine(self.path)
        life = reloaded.state()["npcs"]["hark"]["inner_life"]
        self.assertEqual(len(life["current_emotions"]), 2)
        self.assertEqual(life["relationships"]["ben"]["facets"]["trust"], self.experience()["changes"]["trust"]["after"])
        self.assertNotIn("romantic_interest", life["relationships"]["ben"]["facets"])
        self.assertTrue(reloaded.verify())

    def test_new_mood_does_not_reset_trust_or_auto_create_romance(self):
        self.accept([self.profile(), self.experience()])
        old = self.engine.state()["npcs"]["hark"]["inner_life"]
        experience = self.experience(changes={})
        experience["observed"] = "班提到等待交班很累。"
        experience["interpretation"] = "讓他想到延誤的工作。"
        experience["emotions"] = ["疲憊與焦急"]
        self.accept([experience])
        new = self.engine.state()["npcs"]["hark"]["inner_life"]
        self.assertEqual(new["relationships"], old["relationships"])
        self.assertEqual(new["current_emotions"][0]["feeling"], "疲憊與焦急")
        self.assertEqual(len(new["memories"]), 2)
        self.assertEqual(new["personality"], old["personality"])

    def test_own_memory_can_influence_later_emotion(self):
        self.accept([self.profile(), self.experience()])
        life = self.engine.state()["npcs"]["hark"]["inner_life"]
        old_trust = life["relationships"]["ben"]["facets"]["trust"]
        memory_id = life["memories"][0]["id"]
        experience = self.experience(recalls=[memory_id], changes={"affection": {"before": None, "after": "開始喜歡班願意體諒人的一面；尚未形成浪漫感情"}})
        experience["observed"] = "班再次提到先前那次道謝的意思。"
        experience["interpretation"] = "讓他想起被理解的感覺，而不只是一句例行客套。"
        self.accept([experience])
        relation = self.engine.state()["npcs"]["hark"]["inner_life"]["relationships"]["ben"]
        self.assertEqual(relation["facets"]["trust"], old_trust)
        self.assertNotIn("commitment", relation["facets"])
        self.assertEqual(relation["history"][-1]["memory"], "social-2-0")

    def test_unknown_memory_and_remote_omniscience_rejected(self):
        with self.assertRaises(RuleError):
            self.accept([self.experience(recalls=["invented-memory"])])
        self.engine.submit({"kind": "travel", "destination": "shelter", "text": "我去避雨棚。"}, "walk", 0)
        with self.assertRaises(RuleError):
            self.engine.propose({"kind": "freeform", "text": "我想著哈克。"}, {
                "outcome": "success", "reason": "測試不在場感知", "narration": "無新事件。",
                "events": [self.experience()]}, 1)

    def test_romance_exclusion_does_not_prohibit_affection(self):
        limits = [{"subject": "ben", "facet": "romantic_interest", "reason": "此獨立測試人物對班的既定浪漫取向不相容；不是因為在值勤"}]
        self.accept([self.profile(limits=limits), self.experience(changes={"affection": {"before": None, "after": "真心感激，願意保持友誼"}})])
        with self.assertRaises(RuleError):
            self.accept([self.experience(changes={"romantic_interest": {"before": None, "after": "因送禮而自動愛上班"}})])
        life = self.engine.state()["npcs"]["hark"]["inner_life"]
        self.assertIn("affection", life["relationships"]["ben"]["facets"])
        self.assertNotIn("romantic_interest", life["relationships"]["ben"]["facets"])

    def test_romance_can_develop_without_auto_commitment(self):
        self.accept([self.profile(), self.experience(changes={"romantic_interest": {"before": None, "after": "發現自己期待下次見面，但還沒準備好作出關係承諾"}})])
        npc = self.engine.state()["npcs"]["hark"]
        life = npc["inner_life"]
        self.assertIn("romantic_interest", life["relationships"]["ben"]["facets"])
        self.assertNotIn("commitment", life["relationships"]["ben"]["facets"])
        self.assertEqual(life["attraction_baseline"]["text"], "目前沒有建立吸引；不等於敵意")
        self.assertIn("facets", npc["encounter"]["attraction"])
        self.assertEqual(npc["encounter"]["priorities"], "等候交班並維持城門秩序")

    def test_no_numeric_love_points(self):
        for value in (90, "90", "90%", "90/100"):
            with self.assertRaises(RuleError):
                self.accept([self.experience(changes={"affection": {"before": None, "after": value}})])

    def test_established_personality_cannot_be_reset_on_next_request(self):
        self.accept([self.profile(), self.experience()])
        with self.assertRaises(RuleError):
            self.accept([self.profile()])
        with self.assertRaises(RuleError):
            self.accept([{"type": "personality_change", "npc": "hark", "before": self.profile()["description"],
                          "after": "無條件答應班的要求", "basis": "玩家希望如此", "memory_ids": []}])

    def test_deep_personality_change_needs_preexisting_experience(self):
        self.accept([self.profile(), self.experience()])
        life = self.engine.state()["npcs"]["hark"]["inner_life"]
        self.accept([{"type": "personality_change", "npc": "hark", "before": life["personality"]["description"],
                      "after": "更能相信有人願意幫忙，仍會衡量自己能否履行承諾。",
                      "basis": "經先前已接受的體諒經歷後，開始重新看待接受協助。",
                      "memory_ids": [life["memories"][0]["id"]]}])
        new = self.engine.state()["npcs"]["hark"]["inner_life"]
        self.assertEqual(new["personality_history"][0], life["personality"])
        self.assertNotEqual(new["personality"], life["personality"])

    def test_relationships_are_directional_and_not_global(self):
        npc = copy.deepcopy(self.engine.state()["npcs"]["hark"])
        npc["id"], npc["name"] = "mira", "米拉（Mira）"
        experience = self.experience(subject="mira", changes={"trust": {"before": None, "after": "願意相信米拉會守約"}})
        experience["observed"] = "米拉當面向哈克重申她願意遵守交班約定。"
        experience["interpretation"] = "哈克覺得她重視自己的承諾，仍要看是否履行。"
        self.accept([{"type": "establish_npc", "npc": npc}, self.profile(), self.profile("mira"), experience])
        npcs = self.engine.state()["npcs"]
        self.assertIn("mira", npcs["hark"]["inner_life"]["relationships"])
        self.assertNotIn("ben", npcs["hark"]["inner_life"]["relationships"])
        self.assertEqual(npcs["mira"]["inner_life"]["relationships"], {})
        self.assertEqual(npcs["mira"]["inner_life"]["memories"], [])
        hark_memory = npcs["hark"]["inner_life"]["memories"][0]["id"]
        with self.assertRaises(RuleError):
            self.accept([self.experience(npc="mira", recalls=[hark_memory])])

    def test_duplicate_approval_and_rewind_preserve_emotional_history(self):
        p, first = self.accept([self.profile(), self.experience()])
        second = self.engine.approve(p["id"], "accepted-1")
        self.assertEqual(first, second)
        self.assertEqual(len(self.engine.state()["npcs"]["hark"]["inner_life"]["memories"]), 1)
        self.engine.rewind(0, 1, "repair")
        self.assertNotIn("inner_life", self.engine.state()["npcs"]["hark"])
        self.assertEqual(len(self.engine.history()), 2)
        self.assertTrue(self.engine.verify())

    def test_public_view_does_not_reveal_private_feelings(self):
        self.accept([self.profile(), self.experience()])
        self.assertNotIn("inner_life", self.engine.public_state()["npcs"]["hark"])

    def test_prompt_retrieval_keeps_canonical_relationship_and_bounds_memories(self):
        self.accept([self.profile(), self.experience()])
        for i in range(7):
            experience = self.experience(changes={})
            experience["observed"] = f"本次測試共同經歷 {i}"
            self.accept([experience])
        original = self.engine.state()
        context = model_context(original, self.action(), memory_limit=3)
        retrieved = context["npcs"]["hark"]["inner_life"]
        self.assertEqual(len(retrieved["memories"]), 3)
        self.assertEqual(retrieved["relationships"]["ben"]["facets"], original["npcs"]["hark"]["inner_life"]["relationships"]["ben"]["facets"])
        self.assertEqual(len(original["npcs"]["hark"]["inner_life"]["memories"]), 8)
        self.assertEqual(original, self.engine.state())

    def test_loading_old_campaign_does_not_invent_emotions_or_rewrite_history(self):
        before = self.engine.state()
        again = Engine(self.path)
        self.assertEqual(again.state(), before)
        self.assertEqual(again.history(), [])
        self.assertEqual(inner_life(before["npcs"]["hark"])["relationships"], {})

    def test_duty_is_not_a_programmed_refusal_and_npc_move_keeps_relationship(self):
        self.accept([self.profile(), self.experience()])
        before = self.engine.state()
        self.accept([{"type": "npc_move", "npc": "hark", "from": "gate", "destination": "shelter",
                      "basis": "此獨立測試的已接受裁定：哈克權衡後願在仍能看見城門的相鄰雨棚短暫交談，承擔離開門燈位置的風險。"}])
        after = self.engine.state()
        self.assertEqual(after["pc"]["location"], "gate")
        self.assertEqual(after["npcs"]["hark"]["location"], "shelter")
        self.assertEqual(after["npcs"]["hark"]["inner_life"], before["npcs"]["hark"]["inner_life"])

    def test_npc_cannot_teleport_for_convenient_social_outcome(self):
        with self.assertRaises(RuleError):
            self.accept([{"type": "npc_move", "npc": "hark", "from": "gate", "destination": "unknown_tavern",
                          "basis": "為了讓邀請成功而忽略地理"}])


if __name__ == "__main__":
    unittest.main()
