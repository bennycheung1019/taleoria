import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kobold_rpg.engine import Engine
from kobold_rpg.gm import EntryContinuityError,establish_details,reply as gm_reply
from kobold_rpg.library import CampaignLibrary
from kobold_rpg.npc_visibility import hide_name
from kobold_rpg.worldgen import build_world
from test_library import fixture


class NPCVisibilityTests(unittest.TestCase):
    def test_preexisting_acquaintance_knows_name_and_has_card_at_opening(self):
        candidate=fixture();plan=candidate['plan']
        plan['player']['background']='阿晴在河邊住了十年，與小禾是多年朋友。'
        plan['npc']['known_to_player']=True
        plan['npc']['relationship_to_player']='阿晴與小禾在河邊相識多年，常互相照看藥草。'
        plan['opening']='小禾在門內整理藥草，向老朋友揮手說：「今日有新鮮藥草。」'
        candidate['seed']=build_world(plan,candidate['preferences'])
        with tempfile.TemporaryDirectory() as folder:
            original=Engine(Path(folder)/'original.sqlite3',seed=candidate['seed'])
            library=CampaignLibrary(Path(folder)/'library',original)
            preview=library.preview(candidate)
            self.assertIn('小禾',preview['plan']['opening'])
            library.create(preview['preview_id'])
            state=library.engine.state()
            self.assertTrue(state['npcs']['guide']['name_known'])
            self.assertEqual(library.engine.public_state()['people']['guide']['name'],'小禾（Xiao He）')
            self.assertIn('小禾',library.engine.history()[0]['narration'])
            self.assertIn('小禾',state['facts'][0]['text'])
            self.assertTrue(library.engine.verify())

    def test_prior_acquaintance_requires_named_shared_history(self):
        candidate=fixture();candidate['plan']['npc']['known_to_player']=True
        with self.assertRaisesRegex(ValueError,'既定共同經歷'):
            build_world(candidate['plan'],candidate['preferences'])
        candidate['plan']['npc']['relationship_to_player']='阿晴與小禾相識多年。'
        candidate['preferences']['player_background']='阿晴一直認識小禾。'
        self.assertTrue(build_world(candidate['plan'],candidate['preferences'])['npcs']['guide']['name_known'])

    def test_hidden_name_does_not_invent_player_given_nickname(self):
        npc={'name':'阿海（Ah Hai）','name_known':False,
             'public_name':'一名年輕漁民','description':'一名年輕漁民走近。'}
        shown=hide_name('那年輕漁民——你稱呼他為阿海——衝到你面前。阿海喘著氣。',npc)
        self.assertEqual(shown,'那年輕漁民衝到你面前。一名年輕漁民喘著氣。')

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
                'stance':'願意交談','concern':'菜園收成','knowledge':[],
                'entry_from':'start'}
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

    def test_market_person_needs_witnessed_arrival_before_local_interaction(self):
        state=fixture()['seed']
        state['locations']['near_1']['name']='漁市場（Fish Market）'
        person={'id':'npc_1_1','name':'阿海（Ah Hai）','species':'人類','role':'年輕漁民',
                'description':'一名年輕漁民，穿著灰色短襖。','activity':'趕來木屋',
                'stance':'願意交談','concern':'市場爭執','knowledge':[],
                'entry_from':'near_1'}
        narration='老者口中的年輕人突然在你面前回答：「因為你是劍客。」'
        draft={'establish':{'people':[person]},'narration':narration,'changes':{}}
        with self.assertRaises(EntryContinuityError):
            establish_details(state,draft)
        claimed=copy.deepcopy(draft)
        claimed['narration']='老者說：「年輕漁民從市場跑到木屋門前。」年輕人回答你。'
        with self.assertRaises(EntryContinuityError):
            establish_details(state,claimed)
        wrong_origin=copy.deepcopy(draft)
        wrong_origin['establish']['people'][0]['entry_from']='start'
        wrong_origin['narration']='年輕漁民從市場跑到木屋門前，停下腳步後才回答。'
        with self.assertRaises(EntryContinuityError):
            establish_details(state,wrong_origin)
        still_remote=copy.deepcopy(wrong_origin)
        still_remote['narration']='年輕漁民站在漁市場路邊，向你揮手。'
        with self.assertRaises(EntryContinuityError):
            establish_details(state,still_remote)
        arrived=copy.deepcopy(draft)
        arrived['narration']='年輕漁民從市場跑到木屋門前，停下腳步後才回答你。'
        prepared=establish_details(state,arrived)
        self.assertEqual(prepared['changes']['npcs']['npc_1_1']['location'],'start')
        approached=copy.deepcopy(draft)
        approached['narration']='年輕漁民阿海喘著粗氣，快步走到你面前，才開口回答。'
        self.assertEqual(establish_details(state,approached)['changes']['npcs']['npc_1_1']['location'],'start')

    def test_gm_retries_unwitnessed_person_before_any_story_is_saved(self):
        state=fixture()['seed']
        state['locations']['near_1']['name']='漁市場（Fish Market）'
        person={'id':'npc_1_1','name':'阿海（Ah Hai）','species':'人類','role':'年輕漁民',
                'description':'一名年輕漁民，穿著灰色短襖。','activity':'趕來木屋',
                'stance':'願意交談','concern':'市場爭執','knowledge':[],
                'entry_from':'near_1'}
        bad={'player_power_uses':[],'establish':{'people':[person]},
             'narration':'年輕人突然在你面前回答。','changes':{}}
        good={**bad,'narration':'年輕漁民從市場跑到木屋門前，停下腳步才回答。'}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=state)
            with (patch('kobold_rpg.model._complete',side_effect=[bad,good]) as model,
                  patch('kobold_rpg.context_budget.budget',return_value=None)):
                result=gm_reply(engine.state(),'我問他為何來找我','http://none')
            self.assertEqual(model.call_count,2)
            self.assertIn('從市場跑到木屋門前',result['narration'])
            self.assertEqual(engine.state()['revision'],0)
            self.assertTrue(engine.verify())


if __name__=='__main__':unittest.main()
