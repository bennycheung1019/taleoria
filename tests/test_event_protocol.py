import copy,unittest
from unittest.mock import patch
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import RuleError,validate_proposal
from kobold_rpg.play import interpret
from kobold_rpg.model import react


class EventProtocolTests(unittest.TestCase):
    def setUp(self):
        self.state=new_campaign();self.action=interpret(self.state,'"you should start working, man"')
        self.reply={'outcome':'success','reason':'回應本次話語。','narration':'哈克說：「先離遠一點，我才能繼續工作。」','events':[]}

    def test_missing_type_and_required_event_fields_raise_a_controlled_error(self):
        for event in [{},{'npc':'hark','field':'stance','value':'警戒'},{'type':None},
                      {'type':['npc_update']},{'type':'harm'},{'type':'npc_update','npc':'hark'},
                      {'type':'npc_update','npc':'hark','field':[],'value':'警戒'},
                      {'type':'npc_update','npc':['hark'],'field':'stance','value':'警戒'}]:
            before=copy.deepcopy(self.state)
            with self.assertRaises(RuleError):validate_proposal(self.state,self.action,{**self.reply,'events':[event]})
            self.assertEqual(self.state,before)

    def test_invalid_optional_dialogue_metadata_is_skipped_without_regenerating_speech(self):
        bad={**self.reply,'events':[{'npc':'hark','field':'stance','value':'警戒'}]}
        with patch('kobold_rpg.model._complete',side_effect=[bad,self.reply]) as model:
            result=react(self.state,self.action,'local')
        self.assertEqual(model.call_count,1);self.assertEqual(result,self.reply);self.assertEqual(self.state['revision'],0)

    def test_invalid_optional_event_never_applies_or_blocks_valid_speech(self):
        with patch('kobold_rpg.model._complete',return_value={**self.reply,'events':[{}]}) as model:
            self.assertEqual(react(self.state,self.action,'local'),self.reply)
        self.assertEqual(model.call_count,1);self.assertEqual(self.state['revision'],0)

    def test_malformed_optional_metadata_cannot_break_a_valid_reply(self):
        bad=[{'type':'npc_update','npc':['hark'],'field':'stance','value':'警戒'},
             {'type':'npc_update','npc':'hark','field':'stance','value':[]},
             {'type':['npc_update']},'invalid']
        with patch('kobold_rpg.model._complete',return_value={**self.reply,'events':bad}) as model:
            self.assertEqual(react(self.state,self.action,'local'),self.reply)
        self.assertEqual(model.call_count,1)


if __name__=='__main__':unittest.main()
