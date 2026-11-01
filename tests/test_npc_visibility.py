import copy
import json
import tempfile
import unittest
from pathlib import Path

from kobold_rpg.engine import Engine
from kobold_rpg.gm import establish_details
from kobold_rpg.library import CampaignLibrary
from test_library import fixture


class NPCVisibilityTests(unittest.TestCase):
    def test_opening_and_card_wait_for_spoken_introduction(self):
        candidate=fixture()
        candidate['plan']['player']['background'] += '小禾尚未認識這位旅人。'
        candidate['seed']['locations']['start']['description'] += '小禾在店內。'
        candidate['seed']['facts'].append({'text':'小禾在店內。','visibility':'public','source':'test'})
        with tempfile.TemporaryDirectory() as folder:
            original=Engine(Path(folder)/'original.sqlite3',seed=candidate['seed'])
            library=CampaignLibrary(Path(folder)/'library',original)
            preview=library.preview(candidate)
            self.assertNotIn('小禾',json.dumps(preview,ensure_ascii=False))
            self.assertIn('幾位居民',preview['plan']['opening'])
            library.create(preview['preview_id'])
            engine=library.engine
            self.assertNotIn('小禾',json.dumps(engine.public_state(),ensure_ascii=False))
            self.assertNotIn('小禾',engine.history()[0]['narration'])
            self.assertEqual(engine.public_state()['people'],{})
            engine.record_gm_reply('你叫咩名？',{'narration':'店主說：「我叫小禾。」','changes':{}},'intro',1)
            card=engine.public_state()['people']['guide']
            self.assertEqual(card['name'],'小禾（Xiao He）')
            self.assertEqual(card['description'],candidate['plan']['npc']['description'])
            engine.record_gm_reply('謝謝',{'narration':'小禾點了點頭。',
                'changes':{'npcs':{'guide':{'name_known':False,'public_name':'未知'}}}},'later',2)
            self.assertTrue(engine.state()['npcs']['guide']['name_known'])
            self.assertEqual(engine.public_state()['people']['guide']['name'],'小禾（Xiao He）')
            self.assertTrue(engine.verify())

    def test_crowd_person_appears_locally_without_name_until_introduction(self):
        candidate=fixture();state=copy.deepcopy(candidate['seed'])
        person={'id':'npc_1_1','name':'老陳（Old Chen）','species':'人類','role':'農夫',
                'description':'一位鬚髮花白的農夫，提著菜籃。','activity':'從居民中走近',
                'stance':'願意交談','concern':'菜園收成','knowledge':[]}
        draft={'establish':{'people':[person]},'narration':'老陳從附近人群走近，向你點頭。',
               'changes':{'npcs':{'npc_1_1':{'location':'near_1'}}}}
        prepared=establish_details(state,draft)
        self.assertEqual(prepared['changes']['npcs']['npc_1_1']['location'],'start')
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'world.sqlite3',seed=state)
            first=engine.record_gm_reply('附近有人嗎？',prepared,'new-person',0)
            self.assertNotIn('老陳',first['narration'])
            self.assertIn('鬚髮花白的農夫',first['narration'])
            self.assertNotIn('npc_1_1',engine.public_state()['people'])
            engine.record_gm_reply('你叫咩名？',{'narration':'那位農夫說：「我叫老陳。」','changes':{}},'name',1)
            self.assertEqual(engine.public_state()['people']['npc_1_1']['name'],'老陳（Old Chen）')
            self.assertTrue(engine.verify())


if __name__=='__main__':unittest.main()
