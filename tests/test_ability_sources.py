import copy
import json
import unittest
from unittest.mock import patch
from kobold_rpg.ability_sources import inspect_reply, source_for
from kobold_rpg.campaign import new_campaign
from kobold_rpg.gm import reply


def response(text,uses=None,changes=None):
    return {'player_power_uses':uses or [],'narration':text,'changes':changes or {}}


class AbilitySourceTests(unittest.TestCase):
    def setUp(self):self.state=new_campaign()

    def test_catalog_entry_alone_does_not_grant_ownership(self):
        self.state['abilities']['fire']={'name':'火焰術','source':'學院教材','effect':'小火焰'}
        self.assertIsNone(source_for(self.state,'fire'))
        self.state['pc']['spells']=['fire']
        self.assertEqual(source_for(self.state,'fire')['kind'],'learned_spell')

    def test_canonical_power_requires_ownership_source_and_prior_establishment(self):
        self.state['canon']['actors']['ben']['powers']=['spark']
        definition={'actor':'ben','source':'已接受的初始角色設定','effect':'微弱光點','established_revision':1}
        self.state['canon']['powers']['spark']=definition
        self.assertIsNone(source_for(self.state,'spark'))
        definition['established_revision']=0
        self.assertEqual(source_for(self.state,'spark')['kind'],'registered_power')
        definition['actor']='hark'
        self.assertIsNone(source_for(self.state,'spark'))

    def test_unsupported_effect_is_corrected_before_any_world_changes(self):
        original='我扣好斗篷，再對空地嘗試施放火焰術。'
        draft=response('空地燃起火焰。',[{'ability_id':'fire','manifested':True}],
            {'pc':{'spells':['fire']},'abilities':{'fire':{'source':'這次突然覺醒','effect':'大火'}},
             'facts_add':['空地被火焰燒過。']})
        fixed=response('你扣好斗篷，嘗試施法，但沒有產生火焰。',[{'ability_id':'fire','manifested':False}],
                       {'pc':{'equipment_notes':'斗篷已扣好，獵刀和繩索仍在。'}})
        before=copy.deepcopy(self.state)
        with patch('kobold_rpg.model._complete',side_effect=[draft,fixed]) as model:
            result=reply(self.state,original,'http://local')
        self.assertEqual(model.call_count,2)
        self.assertEqual(result['narration'],fixed['narration'])
        self.assertEqual(result['changes'],fixed['changes'])
        self.assertTrue(result['ability_source_correction'])
        self.assertEqual(model.call_args.args[0][-1],{'role':'user','content':original})
        self.assertIn('已核對的能力來源結果',model.call_args.args[0][0]['content'])
        self.assertNotIn('空地燃起火焰。',json.dumps(model.call_args.args[0],ensure_ascii=False))
        self.assertEqual(self.state,before)

    def test_failed_attempt_cannot_bootstrap_a_power_for_the_next_turn(self):
        result=response('這次還沒有火焰。',[{'ability_id':'fire','manifested':False}],
                        {'pc':{'spells':['fire']},'abilities':{'fire':{'source':'只是嘗試','effect':'火焰'}}})
        self.assertTrue(inspect_reply(self.state,result)[0])

    def test_real_established_power_is_one_generation(self):
        self.state['pc']['spells']=['light']
        self.state['abilities']['light']={'name':'微光術','source':'先前已接受的訓練','effect':'照亮掌心'}
        with patch('kobold_rpg.model._complete',return_value=response('掌心亮起微光。',[{'ability_id':'light','manifested':True}])) as model:
            result=reply(self.state,'我施展微光術。','http://local')
        model.assert_called_once()
        self.assertEqual(result['ability_source_check'][0]['result'],'source_confirmed')

    def test_magic_question_and_ordinary_physical_action_are_not_word_filtered(self):
        for text in ('這裡有人懂火焰魔法嗎？','我用獵刀割開繩子。','我想像自己會飛。'):
            with self.subTest(text=text),patch('kobold_rpg.model._complete',return_value=response('哈克抬頭回應。')) as model:
                result=reply(self.state,text,'http://local')
                model.assert_called_once();self.assertFalse(result.get('ability_source_correction',False))
                self.assertEqual(model.call_args.args[0][-1]['content'],text)

    def test_second_invalid_effect_has_bounded_nonmagical_fallback(self):
        bad=response('魔法發生了。',[{'ability_id':'unknown','manifested':True}],{'facts_add':['魔法發生。']})
        with patch('kobold_rpg.model._complete',return_value=bad) as model:
            result=reply(self.state,'我嘗試超自然力量。','http://local')
        self.assertEqual(model.call_count,2)
        self.assertEqual(result['changes'],{})
        self.assertIn('沒有產生相應效果',result['narration'])


if __name__=='__main__':unittest.main()
