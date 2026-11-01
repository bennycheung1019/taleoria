import copy
import json
from pathlib import Path
import tempfile
import unittest
from kobold_rpg.engine import Engine, RuleError
from kobold_rpg.campaign import new_campaign
from kobold_rpg.worldgen import preferences


class PlayerKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        seed=new_campaign()
        seed['locations']['secret']={'name':'不應洩漏的密室','description':'密室內有秘密。','exits':{}}
        seed['locations']['gate']['exits']['secret']={'known':False,'clear':True}
        seed['npcs']['hark']['anchor']['concern']='不可自動公開的秘密'
        self.engine=Engine(Path(self.tmp.name)/'world.db',seed=seed)

    def test_map_has_only_known_links_and_no_false_coordinates(self):
        view=self.engine.public_state()
        self.assertNotIn('secret',view['locations'])
        self.assertNotIn('不應洩漏的密室',json.dumps(view,ensure_ascii=False))
        self.assertEqual({p['id'] for p in view['atlas']['nodes']},{'gate','shelter','river_street','pier'})
        self.assertEqual(sum(n['current'] for n in view['atlas']['nodes']),1)
        self.assertIn('不代表實際距離',view['atlas']['scale'])

    def test_people_do_not_reveal_unmet_npcs_or_private_inner_life(self):
        view=self.engine.public_state()
        self.assertEqual(set(view['people']),{'hark'})
        self.assertEqual(set(view['npcs']),{'hark'})
        self.assertNotIn('不可自動公開的秘密',json.dumps(view,ensure_ascii=False))
        self.assertNotIn('inner_life',view['npcs']['hark'])

    def proposal(self,quote='弟弟還在家裡等我。'):
        return {'outcome':'success','reason':'哈克公開回答。','narration':'哈克說：「'+quote+'」',
                'events':[{'type':'character_note','npc':'hark','kind':'said','quote':quote}]}


class CreationDefaultsTests(unittest.TestCase):
    def test_removed_knobs_are_derived_from_story_type(self):
        result=preferences({'genre':'日常小鎮','tone':'不要採納的值','magic':'偷偷加入魔法','difficulty':'一般'})
        self.assertEqual(result['magic'],'沒有超自然能力')
        self.assertIn('日常',result['tone'])

    def test_free_description_can_explicitly_override_type_default(self):
        result=preferences({'genre':'日常小鎮','wishes':'我想加入少量魔法，魔法要先建立來源。'})
        self.assertNotEqual(result['magic'],'沒有超自然能力')

    def test_difficulty_has_distinct_preparation_guidance_without_scores(self):
        values=[preferences({'genre':'黑暗奇幻','difficulty':name}) for name in ['以故事體驗為主','一般','困難']]
        self.assertEqual(len({v['difficulty_guidance'] for v in values}),3)
        self.assertIn('線索',values[0]['difficulty_guidance'])
        self.assertIn('資源較緊',values[2]['difficulty_guidance'])


if __name__=='__main__':unittest.main()
