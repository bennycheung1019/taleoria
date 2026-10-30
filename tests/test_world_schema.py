import copy,io,json,unittest
from unittest.mock import patch
from kobold_rpg.engine import RuleError
from kobold_rpg.model import _complete,InvalidJSONError
from kobold_rpg.worldgen import generate_world
from kobold_rpg.world_schema import WORLD_SCHEMA,obj,text
from test_library import fixture


class WorldSchemaTests(unittest.TestCase):
    def test_schema_is_sent_in_the_existing_request_without_an_extra_model_call(self):
        response=io.BytesIO(json.dumps({'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}]}).encode())
        schema=obj({'ok':{'type':'boolean'}})
        with patch('kobold_rpg.model.urllib.request.urlopen',return_value=response) as request:
            result=_complete([{'role':'user','content':'test'}],'http://local',40,.1,response_schema=schema)
        self.assertEqual(result,{'ok':True});self.assertEqual(request.call_count,1)
        payload=json.loads(request.call_args.args[0].data)
        self.assertEqual(payload['response_format']['json_schema']['schema'],schema)
        self.assertEqual(payload['response_format']['type'],'json_schema')

    def test_world_creation_uses_full_blueprint_constraints(self):
        candidate=fixture()
        with patch('kobold_rpg.worldgen._complete',return_value=candidate['plan']) as complete,patch('kobold_rpg.worldgen.audit_narration',return_value=candidate['audit']) as audit:
            result=generate_world(candidate['preferences'],'http://local')
        self.assertEqual(complete.call_count,1)
        schema=complete.call_args.kwargs['response_schema']
        self.assertIn('阿晴',schema['properties']['player']['properties']['name']['pattern'])
        self.assertEqual(schema['properties']['npc'],WORLD_SCHEMA['properties']['npc'])
        self.assertEqual([m['role'] for m in complete.call_args.args[0]],['system','user'])
        self.assertIn('RPG OS v1.01 原規則摘錄',complete.call_args.args[0][0]['content'])
        self.assertTrue(audit.call_args.kwargs['structured'])
        self.assertEqual(result['plan'],candidate['plan'])

    def test_english_player_preference_is_preserved_with_a_chinese_alias(self):
        candidate=fixture();plan=copy.deepcopy(candidate['plan']);plan['player']['name']='班尼（Benny）'
        prefs={**candidate['preferences'],'player_name':'Benny'}
        with patch('kobold_rpg.worldgen._complete',return_value=plan),patch('kobold_rpg.worldgen.audit_narration',return_value=candidate['audit']):
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
