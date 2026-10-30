import copy
import json
from pathlib import Path
import tempfile
import unittest
from kobold_rpg.engine import Engine, RuleError
from kobold_rpg.campaign import new_campaign
from kobold_rpg.canon import digest
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

    def test_people_remain_in_book_and_last_seen_does_not_follow_secret_movement(self):
        self.engine.submit({'kind':'observe','text':'環顧四周'},'look',0)
        self.engine.submit({'kind':'travel','text':'前往河街','destination':'river_street'},'walk',1)
        self.engine.submit({'kind':'travel','text':'前往渡口','destination':'pier'},'pier',2)
        view=self.engine.public_state()
        self.assertEqual(set(view['people']),{'hark','anya'})
        self.assertEqual(view['people']['hark']['last_seen'],'霧橋鎮北門（Mistbridge North Gate）')
        self.assertNotIn('hark',view['npcs'])
        self.assertEqual(view['atlas']['origin'],'gate')
        self.assertTrue(next(n for n in view['atlas']['nodes'] if n['id']=='gate')['visited'])

    def proposal(self,quote='弟弟還在家裡等我。'):
        return {'outcome':'success','reason':'哈克公開回答。','narration':'哈克說：「'+quote+'」',
                'events':[{'type':'character_note','npc':'hark','kind':'said','quote':quote}]}

    def test_new_information_is_only_added_after_approval_and_is_a_claim(self):
        proposal=self.proposal();audit={'revision':0,'proposal_hash':digest(proposal),
            'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
        draft=self.engine.propose({'kind':'speak','target':'hark','text':'我問他為何急著回家。'},proposal,0,audit=audit)
        self.assertEqual(len(self.engine.public_state()['people']['hark']['facts']),1)
        self.engine.approve(draft['id'],'approve')
        note=self.engine.public_state()['people']['hark']['facts'][-1]
        self.assertEqual(note['kind'],'said');self.assertEqual(note['quote'],'弟弟還在家裡等我。')
        self.assertNotIn('verified',note.values())
        self.assertTrue(self.engine.verify())

    def test_notes_cannot_copy_private_material_or_come_from_unmet_people(self):
        for change in ({'npc':'anya'},{'quote':'不可自動公開的秘密'}):
            proposal=self.proposal();proposal['events'][0].update(change)
            with self.assertRaises(RuleError):
                self.engine.propose({'kind':'speak','target':'hark','text':'你好。'},proposal,0)
        self.assertEqual(self.engine.state()['revision'],0)


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
