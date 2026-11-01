import copy,io,json,re,unittest
from unittest.mock import patch
from kobold_rpg.engine import RuleError
from kobold_rpg.model import _complete,InvalidJSONError
from kobold_rpg.worldgen import generate_world
from kobold_rpg.world_schema import WORLD_SCHEMA,obj,text,BILINGUAL_NAME
from test_library import fixture


class WorldSchemaTests(unittest.TestCase):
    def test_bilingual_pattern_cannot_consume_json_delimiters_or_later_fields(self):
        pattern=BILINGUAL_NAME['pattern']
        for name in ['雨港（Rain Port）',"阿晴（Ah Ching）","瑪莉（Mary-Jane O'Neil）"]:
            self.assertIsNotNone(re.fullmatch(pattern,name))
        for prefix in ['雨港", "description": "另一欄','雨港\\','雨港\n','雨港\x00']:
            self.assertIsNone(re.fullmatch(pattern,prefix+'（Rain Port）'))

    def test_requested_english_name_prefix_cannot_consume_the_rest_of_the_plan(self):
        candidate=fixture();plan=copy.deepcopy(candidate['plan']);plan['player']['name']='班尼（Benny）'
        with patch('kobold_rpg.worldgen._complete',return_value=plan) as complete:
            generate_world({**candidate['preferences'],'player_name':'Benny'},'http://local')
        pattern=complete.call_args.kwargs['response_schema']['properties']['player']['properties']['name']['pattern']
        self.assertIsNotNone(re.fullmatch(pattern,'班尼（Benny）'))
        self.assertIsNone(re.fullmatch(pattern,'班尼", "role": "旅人（Benny）'))

    def test_schema_is_sent_in_the_existing_request_without_an_extra_model_call(self):
        response=io.BytesIO(json.dumps({'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}]}).encode())
        schema=obj({'ok':{'type':'boolean'}})
        with patch('kobold_rpg.model.urllib.request.urlopen',return_value=response) as request:
            result=_complete([{'role':'user','content':'test'}],'http://local',40,.1,response_schema=schema)
        self.assertEqual(result,{'ok':True});self.assertEqual(request.call_count,1)
        payload=json.loads(request.call_args.args[0].data)
        self.assertEqual(payload['response_format']['json_schema']['schema'],schema)
        self.assertEqual(payload['response_format']['type'],'json_schema')

    def test_world_creation_uses_compact_open_world_without_story_outline(self):
        candidate=fixture()
        with patch('kobold_rpg.worldgen._complete',return_value=candidate['plan']) as complete:
            result=generate_world(candidate['preferences'],'http://local')
        self.assertEqual(complete.call_count,1)
        schema=complete.call_args.kwargs['response_schema']
        self.assertIn('阿晴',schema['properties']['player']['properties']['name']['pattern'])
        self.assertEqual(schema['properties']['location']['properties']['nearby']['maxItems'],1)
        self.assertEqual([m['role'] for m in complete.call_args.args[0]],['system','user'])
        self.assertIn('RPG OS v1.01 原規則摘錄',complete.call_args.args[0][0]['content'])
        self.assertEqual(result['plan'],candidate['plan'])
        self.assertNotIn('audit',result)
        self.assertNotIn('story',result['seed'])

    def test_new_world_uses_familiar_entry_without_copying_prior_prose(self):
        candidate=fixture()
        prior=[{'title':'舊戰役','background':'灰霧籠罩礦區',
                'location':'礦井入口','npc':'年長礦工','opening':'年長礦工在礦井前說話。',
                'entry_frame':'neighborhood','entry_setting':'hill'}]
        with patch('kobold_rpg.worldgen._complete',return_value=candidate['plan']) as complete:
            result=generate_world({**candidate['preferences'],'wishes':'random',
                                   'player_background':'random'},'http://local',prior_worlds=prior)
        request=json.loads(complete.call_args.args[0][1]['content'])
        self.assertEqual(request['玩家偏好']['wishes'],'')
        self.assertEqual(request['玩家偏好']['player_background'],'')
        self.assertNotIn('避免重複',request)
        self.assertNotIn('灰霧',complete.call_args.args[0][1]['content'])
        self.assertNotEqual(result['seed']['world']['entry_frame'],'neighborhood')
        self.assertNotEqual(result['seed']['world']['entry_setting'],'hill')
        system=complete.call_args.args[0][0]['content']
        self.assertIn('第一次接觸這個世界',system)
        self.assertIn('只改人名或建築名稱不算新故事',system)
        self.assertEqual(complete.call_count,1)

    def test_copied_world_is_retried_then_refused_if_still_copied(self):
        candidate=fixture();prior=[{'title':'舊戰役','background':'河港小鎮以渡運與藥草生意維生。',
                                    'location':'河邊店門（Riverside Shop Entrance）',
                                    'npc':'小禾（Xiao He）'}]
        with patch('kobold_rpg.worldgen._complete',return_value=candidate['plan']) as complete:
            with self.assertRaisesRegex(RuleError,'太相似'):
                generate_world({**candidate['preferences'],'wishes':'random'},'http://local',prior_worlds=prior)
        self.assertEqual(complete.call_count,2)

    def test_reworded_setting_motifs_are_also_rejected(self):
        from kobold_rpg.worldgen import _similar_to_prior
        plan=copy.deepcopy(fixture()['plan'])
        plan['background']='城裡的薄霧沾著鐵鏽味，居民照常開店。'
        prior=[{'title':'別的標題','background':'礦坑覆滿灰燼，鋼架已鏽蝕。',
                'location':'另一處','npc':'另一人'}]
        self.assertTrue(_similar_to_prior(plan,prior))

    def test_opening_cut_at_old_limit_is_rewritten_before_creation(self):
        candidate=fixture();plan=copy.deepcopy(candidate['plan'])
        plan['opening']='河水聲。'+'他'*236
        self.assertEqual(len(plan['opening']),240)
        with patch('kobold_rpg.worldgen._complete',side_effect=[
                plan,{'opening':candidate['plan']['opening']}]) as complete:
            result=generate_world(candidate['preferences'],'http://local')
        self.assertEqual(complete.call_count,2)
        self.assertGreater(complete.call_args_list[0].kwargs['response_schema']
                           ['properties']['opening']['maxLength'],240)
        self.assertEqual(result['plan']['opening'],candidate['plan']['opening'])

    def test_incomplete_rewrite_uses_only_established_descriptions(self):
        candidate=fixture();plan=copy.deepcopy(candidate['plan'])
        plan['opening']='未完的開場'
        with patch('kobold_rpg.worldgen._complete',side_effect=[
                plan,{'opening':'仍然未完'}]) as complete:
            result=generate_world(candidate['preferences'],'http://local')
        self.assertEqual(complete.call_count,2)
        self.assertEqual(result['plan']['opening'],
                         plan['location']['description']+'\n\n'+plan['npc']['description'])

    def test_english_player_preference_is_preserved_with_a_chinese_alias(self):
        candidate=fixture();plan=copy.deepcopy(candidate['plan']);plan['player']['name']='班尼（Benny）'
        prefs={**candidate['preferences'],'player_name':'Benny'}
        with patch('kobold_rpg.worldgen._complete',return_value=plan):
            result=generate_world(prefs,'http://local')
        self.assertEqual(result['seed']['pc']['name'],'班尼（Benny）')
        plan['player']['name']='班尼（Other Name）'
        with patch('kobold_rpg.worldgen._complete',return_value=plan):
            with self.assertRaises(RuleError):generate_world(prefs,'http://local')

    def test_incomplete_json_has_a_world_creation_message_and_no_partial_acceptance(self):
        prefs=fixture()['preferences'];before=copy.deepcopy(prefs)
        with patch('kobold_rpg.worldgen._complete',side_effect=InvalidJSONError('JSON failure')):
            with self.assertRaises(RuleError) as error:generate_world(prefs,'http://local')
        self.assertIn('尚未建立或切換世界',str(error.exception));self.assertNotIn('手動裁定',str(error.exception))
        self.assertEqual(prefs,before)

    def test_connection_errors_are_not_mislabelled_as_bad_json(self):
        with patch('kobold_rpg.worldgen._complete',side_effect=RuleError('KoboldCpp 連線失敗')):
            with self.assertRaisesRegex(RuleError,'連線失敗'):generate_world(fixture()['preferences'],'http://local')

    def test_missing_plan_objects_fail_before_name_processing(self):
        with patch('kobold_rpg.worldgen._complete',return_value={'title':'partial'}):
            with self.assertRaises(RuleError):generate_world(fixture()['preferences'],'http://local')


if __name__=='__main__':unittest.main()
