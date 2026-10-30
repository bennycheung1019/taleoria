import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from kobold_rpg.engine import Engine, RuleError
from kobold_rpg.campaign import new_campaign
from kobold_rpg.worldgen import build_world, generate_world, opening_proposal
from kobold_rpg.canon import digest
from kobold_rpg.library import CampaignLibrary
from kobold_rpg.play import interpret


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
                    'attraction': '尚未建立吸引', 'stance': '可以簡短交談'},
            'opening': '河水聲從店外傳來。小禾在門內整理藥草，抬頭說：「你好，需要幫忙嗎？」'}
    seed = build_world(plan, prefs)
    proposal = opening_proposal(plan)
    audit = {'revision': 0, 'proposal_hash': digest(proposal),
             'result': {'supported': True, 'actors': ['ben', 'guide'], 'powers': [], 'issues': []}}
    return {'preferences': prefs, 'plan': plan, 'seed': seed, 'audit': audit}


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

    def test_bad_candidate_cannot_replace_current_world(self):
        candidate = fixture(); candidate['audit']['result']['supported'] = False
        preview = self.library.preview(candidate)
        before = self.library.engine.state()
        with self.assertRaises(RuleError): self.library.create(preview['preview_id'])
        self.assertEqual(self.library.engine.state(), before)

    def test_save_load_restores_complete_journal_without_mutating_snapshot(self):
        self.original.submit({'kind':'observe','text':'我環顧四周。'}, 'look', 0)
        saved = self.library.save('第一次抵達')
        save_path = Path(self.library.index['saves'][saved['id']]['path'])
        self.original.submit({'kind':'travel','text':'前往避雨棚','destination':'shelter'}, 'walk', 1)
        old_session = self.library.session_id
        self.library.load('save', saved['id'])
        self.assertEqual(self.library.engine.state()['revision'], 1)
        self.assertEqual(self.library.engine.state()['pc']['location'], 'gate')
        self.assertNotEqual(old_session, self.library.session_id)
        self.assertNotEqual(self.library.engine.path, save_path)
        self.library.engine.submit({'kind':'observe','text':'再看看。'}, 'look-again', 1)
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
        with patch('kobold_rpg.worldgen._complete',side_effect=[bad,{'opening':candidate['plan']['opening']}]),patch('kobold_rpg.worldgen.audit_narration',return_value=candidate['audit']):
            result=generate_world(candidate['preferences'],'http://127.0.0.1:5001')
        self.assertEqual(result['plan']['opening'],candidate['plan']['opening'])

    def test_model_generation_keeps_preview_separate_and_checks_name(self):
        candidate=fixture()
        with patch('kobold_rpg.worldgen._complete',return_value=candidate['plan']), patch('kobold_rpg.worldgen.audit_narration',return_value=candidate['audit']):
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


class InputTests(unittest.TestCase):
    def setUp(self): self.state=new_campaign()

    def test_free_text_remains_review_and_speech_preserves_original_text(self):
        text='我問哈克：「你最近學會魔法了嗎？」'
        action=interpret(self.state,text)
        self.assertEqual(action['text'],text);self.assertEqual(action['kind'],'speak');self.assertEqual(action['target'],'hark')
        from kobold_rpg.understanding import pack
        self.assertEqual(interpret(self.state,'我想仔細檢查這張紙。',resolver=lambda text:pack('action',text))['kind'],'freeform')

    def test_cast_and_known_item_keep_prerequisite_checks(self):
        self.assertEqual(interpret(self.state,'我使用火焰魔法。')['ability'],'fire_magic')
        self.assertEqual(interpret(self.state,'我使用繩索固定木板。')['item'],'rope')
        self.assertEqual(interpret(self.state,'我環顧四周。')['kind'],'observe')

    def test_unknown_route_does_not_create_a_location(self):
        action=interpret(self.state,'我前往另一個星球。')
        self.assertEqual(action['kind'],'freeform')
        self.assertEqual(action['destination'],'')
        self.assertNotIn('unknown_destination',self.state['locations'])

    def test_presets_do_not_rewrite_text_or_grant_success(self):
        action=interpret(self.state,'我前往避雨棚。',{'kind':'travel','destination':'shelter'})
        self.assertEqual(action['destination'],'shelter')
        self.assertEqual(self.state['pc']['location'],'gate')


if __name__=='__main__': unittest.main()
