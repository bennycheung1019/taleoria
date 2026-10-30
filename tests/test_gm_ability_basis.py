import copy
import json
import unittest
from unittest.mock import patch
from kobold_rpg.campaign import new_campaign
from kobold_rpg.gm import reply, rules_packet


class AbilityBasisTests(unittest.TestCase):
    def test_original_capacity_and_control_rules_are_actually_loaded(self):
        rules=rules_packet()
        self.assertIn('a state adjective supplies no unrecorded skill, statistic or ability',rules)
        self.assertIn('A change of control or lost link requires its supported transition.',rules)

    def test_empty_established_abilities_are_explicit_without_classifying_or_blocking_input(self):
        state=new_campaign();before=copy.deepcopy(state)
        text='我對空地嘗試施展火焰魔法。'
        with patch('kobold_rpg.model._complete',return_value={'narration':'你嘗試施法，空地上沒有產生火焰。','changes':{}}) as model:
            result=reply(state,text,'http://local')
        model.assert_called_once();messages=model.call_args.args[0]
        self.assertEqual(messages[-1],{'role':'user','content':text})
        snapshot=json.loads(messages[0]['content'].split('本回合狀態資料：\n',1)[1].split('\n\n主持與輸出要求：',1)[0])
        abilities=snapshot['current_snapshot']['player_ability_record']
        self.assertEqual(abilities['learned_spells'],[])
        self.assertEqual(abilities['registered_powers'],[])
        self.assertEqual(abilities['ordinary_capabilities'],state['pc']['capabilities'])
        self.assertEqual(result['narration'],'你嘗試施法，空地上沒有產生火焰。')
        self.assertEqual(state,before)

    def test_existing_spell_and_its_source_are_preserved(self):
        state=new_campaign();state['pc']['spells']=['light']
        state['abilities']['light']={'name':'微光術','source':'早先已接受的師徒訓練','effect':'照亮掌心的小光點'}
        with patch('kobold_rpg.model._complete',return_value={'narration':'掌心亮起微光。','changes':{}}) as model:
            reply(state,'我施展已學會的微光術。','http://local')
        snapshot=json.loads(model.call_args.args[0][0]['content'].split('本回合狀態資料：\n',1)[1].split('\n\n主持與輸出要求：',1)[0])
        basis=snapshot['current_snapshot']['player_ability_record']
        self.assertEqual(basis['learned_spells'],['light'])
        self.assertEqual(basis['spell_definitions']['light'],state['abilities']['light'])


if __name__=='__main__':unittest.main()
