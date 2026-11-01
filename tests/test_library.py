import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from kobold_rpg.engine import Engine, RuleError
from kobold_rpg.campaign import new_campaign
from kobold_rpg.worldgen import build_world, generate_world
from kobold_rpg.library import CampaignLibrary


def fixture():
    prefs = {'genre': '日常小鎮', 'tone': '溫暖', 'difficulty': '一般', 'magic': '沒有超自然能力',
             'player_name': '阿晴', 'player_background': '成年旅行藥師', 'wishes': '從河邊藥草店開始。', 'permadeath': False}
    plan = {'title': '河邊的藥草店', 'background': '河港小鎮以渡運與藥草生意維生。', 'rules': ['人物有自己的工作與生活。'],
            'player': {'name': '阿晴（Ah Ching）', 'species': '人類', 'role': '成年旅行藥師', 'background': '以藥草知識謀生的成年旅人。',
                       'goal': '找到安穩生活的地方', 'skills': ['辨認藥草'], 'powers': [],
                       'items': [{'name': '藥草袋', 'description': '普通藥草與布袋，並無魔法效果。'}]},
            'location': {'name': '河邊店門（Riverside Shop Entrance）', 'description': '木門旁有一張長凳，店主正在門內整理藥草。',
                         'nearby': [{'name': '河岸小路（Riverside Path）', 'description': '小路沿河延伸，店門仍在視線內。'}]},
            'npc': {'name': '小禾（Xiao He）', 'species': '人類', 'role': '成年店主', 'description': '成年店主正在整理普通藥草。',
                    'personality': '溫和而務實', 'values': '維持小店', 'concern': '藥草受潮', 'boundary': '先問再碰物品',
                    'levers': '實際的協助', 'condition': '清醒，正在工作', 'priorities': '整理藥草', 'appraisal': '看見門外的旅人',
                    'attraction': '尚未建立吸引', 'stance': '可以簡短交談',
                    'known_to_player':False,'relationship_to_player':'初次見面'},
            'opening': '河水聲從店外傳來。店主在門內整理藥草，抬頭說：「你好，需要幫忙嗎？」'}
    seed = build_world(plan, prefs)
    return {'preferences': prefs, 'plan': plan, 'seed': seed}


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.original = Engine(Path(self.tmp.name) / 'original.db', seed=new_campaign())
        self.library = CampaignLibrary(Path(self.tmp.name) / 'library', self.original)

    def test_preview_does_not_change_or_save_active_world(self):
        before = self.original.state()
        result = self.library.preview(fixture())
        self.assertIn('preview_id', result)
        self.assertEqual(self.library.engine.state(), before)
        self.assertEqual(list((self.library.root/'campaigns').glob('*.sqlite3')), [])

    def test_confirm_builds_isolated_canon_and_opening_exactly_once(self):
        preview = self.library.preview(fixture())
        self.library.create(preview['preview_id'])
        state = self.library.engine.state()
        self.assertEqual(state['revision'], 1)
        self.assertEqual(state['pc']['name'], '阿晴（Ah Ching）')
        self.assertEqual(state['pc']['background'], fixture()['plan']['player']['background'])
        self.assertEqual(set(state['canon']['actors']), {'ben','guide'})
        self.assertEqual(state['canon']['powers'], {})
        self.assertEqual(state['locations']['start']['exits']['near_1']['known'], True)
        self.assertEqual(self.original.state()['revision'], 0)
        self.library.create(preview['preview_id'])
        self.assertEqual(self.library.engine.state()['revision'], 1)
        self.assertTrue(self.library.engine.verify())
        self.assertEqual(len(json.loads(self.library.creation_history_path.read_text())),1)
        self.assertEqual(self.library.recent_worlds()[0]['opening'],fixture()['plan']['opening'])

    def test_opening_rejects_implied_player_position_and_inner_thought(self):
        candidate=fixture()
        for text in ('小禾笑道：「你坐坐吧。」你站在店門口。',
                     '小禾正在整理藥草。你腦海中浮現昨天的事。',
                     '小禾說：「你剛到嗎？」你剛結束工作。'):
            plan=copy.deepcopy(candidate['plan']);plan['opening']=text
            with self.assertRaisesRegex(RuleError,'開場替主角'):
                build_world(plan,candidate['preferences'])

    def test_bad_candidate_cannot_replace_current_world(self):
        candidate = fixture(); candidate['seed']['pc']['location'] = 'missing'
        preview = self.library.preview(candidate)
        before = self.library.engine.state()
        with self.assertRaises(RuleError): self.library.create(preview['preview_id'])
        self.assertEqual(self.library.engine.state(), before)

    def test_save_load_restores_complete_journal_without_mutating_snapshot(self):
        self.original.record_gm_reply('我環顧四周。',{'narration':'雨落在城門前。','changes':{}},'look',0)
        saved = self.library.save('第一次抵達')
        save_path = Path(self.library.index['saves'][saved['id']]['path'])
        self.original.record_gm_reply('前往避雨棚',{'narration':'你走進避雨棚。','changes':{'pc':{'location':'shelter'}}},'walk',1)
        old_session = self.library.session_id
        self.library.load('save', saved['id'])
        self.assertEqual(self.library.engine.state()['revision'], 1)
        self.assertEqual(self.library.engine.state()['pc']['location'], 'gate')
        self.assertNotEqual(old_session, self.library.session_id)
        self.assertNotEqual(self.library.engine.path, save_path)
        self.library.engine.record_gm_reply('再看看。',{'narration':'雨仍未停。','changes':{}},'look-again',1)
        self.assertEqual(Engine(save_path).state()['revision'], 1)
        self.assertEqual(self.library.engine.state()['revision'], 2)
        self.assertTrue(self.library.engine.verify())

    def test_old_session_is_rejected_even_when_world_id_and_revision_match(self):
        saved = self.library.save('同一刻')
        old_session = self.library.session_id
        self.library.load('save',saved['id'])
        with self.assertRaises(RuleError): self.library.check_session(old_session)
        self.library.check_session(self.library.session_id)

    def test_restart_restores_selected_world_and_metadata_has_no_paths(self):
        preview = self.library.preview(fixture()); self.library.create(preview['preview_id'])
        world_id = self.library.engine.state()['campaign_id']
        restored = CampaignLibrary(self.library.root,self.original)
        self.assertEqual(restored.engine.state()['campaign_id'],world_id)
        self.assertEqual(restored.engine.state()['revision'],1)
        listing = restored.list()
        self.assertTrue(all('path' not in row for rows in listing.values() for row in rows))

    def test_save_names_are_labels_not_file_paths(self):
        result = self.library.save('../../my-world')
        path = Path(self.library.index['saves'][result['id']]['path'])
        self.assertEqual(path.parent,self.library.root/'saves')
        self.assertEqual(path.stem,result['id'])
        for name in ('',None,'x'*101):
            with self.assertRaises(RuleError): self.library.save(name)

    def test_invalid_ids_do_not_load_arbitrary_files(self):
        for kind,key in [('save','../../original.db'),('campaign','../../original.db'),('bad','x')]:
            with self.assertRaises(RuleError): self.library.load(kind,key)


class WorldPlanTests(unittest.TestCase):
    def test_equivalent_goal_label_is_normalized_without_inventing_content(self):
        candidate=fixture();plan=copy.deepcopy(candidate['plan'])
        goal=plan['player'].pop('goal');plan['player']['wishes']=goal
        seed=build_world(plan,candidate['preferences'])
        self.assertEqual(seed['pc']['goal'],goal)

    def test_opening_rejects_english_sentences_and_reserved_player_actions(self):
        candidate=fixture()
        for text in ['The shopkeeper smiled and greeted you warmly.', '你推開藥草店的門，走進屋內。', '阿晴感到很安心。']:
            plan=copy.deepcopy(candidate['plan']);plan['opening']=text
            with self.assertRaises(RuleError):build_world(plan,candidate['preferences'])

    def test_bad_opening_is_rewritten_before_preview(self):
        candidate=fixture();bad=copy.deepcopy(candidate['plan']);bad['opening']='你推開門。'
        with patch('kobold_rpg.worldgen._complete',side_effect=[bad,{'opening':candidate['plan']['opening']}]):
            result=generate_world(candidate['preferences'],'http://127.0.0.1:5001')
        self.assertEqual(result['plan']['opening'],candidate['plan']['opening'])

    def test_model_generation_keeps_preview_separate_and_checks_name(self):
        candidate=fixture()
        with patch('kobold_rpg.worldgen._complete',return_value=candidate['plan']):
            result=generate_world(candidate['preferences'],'http://127.0.0.1:5001')
        self.assertEqual(result['seed']['revision'],0)
        bad=copy.deepcopy(candidate['plan']);bad['player']['name']='錯誤姓名'
        with patch('kobold_rpg.worldgen._complete',return_value=bad):
            with self.assertRaises(RuleError): generate_world(candidate['preferences'],'http://127.0.0.1:5001')

    def test_incomplete_character_and_forbidden_magic_are_not_accepted(self):
        candidate=fixture();plan=copy.deepcopy(candidate['plan']);plan['npc'].pop('boundary')
        with self.assertRaises(RuleError): build_world(plan,candidate['preferences'])
        plan=copy.deepcopy(candidate['plan']);plan['player']['powers']=[{'name':'火','effect':'生火','limits':'小火'}]
        with self.assertRaises(RuleError): build_world(plan,candidate['preferences'])

    def test_accepted_starting_power_is_registered_before_opening(self):
        candidate=fixture();prefs={**candidate['preferences'],'genre':'黑暗奇幻'}
        plan=copy.deepcopy(candidate['plan']);plan['player']['powers']=[{'name':'微光術','effect':'掌心發出微光','limits':'只照明，沒有傷害'}]
        seed=build_world(plan,prefs)
        self.assertEqual(seed['canon']['powers']['power_1']['established_revision'],0)
        self.assertEqual(seed['pc']['spells'],['power_1'])
        self.assertIn('只照明',seed['abilities']['power_1']['effect'])


if __name__=='__main__': unittest.main()
