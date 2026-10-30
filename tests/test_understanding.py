import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine,RuleError,normalize_action,check_action
from kobold_rpg.play import interpret
from kobold_rpg.physical import attacking
from kobold_rpg.understanding import pack,validate_understanding
from kobold_rpg.model import enrich_characters


class UnderstandingTests(unittest.TestCase):
    def setUp(self):self.state=new_campaign()

    def test_questions_with_violent_words_are_speech_without_a_model_call(self):
        resolver=Mock(side_effect=AssertionError('clear grammar needs no model'))
        for text in ['why would i want to kill you','Why would I stab you?','Can you kill him?','Do you think I want to hurt you?','為什麼我要殺你？','我問哈克：「你為何認為我要殺你？」']:
            action=interpret(self.state,text,resolver=resolver)
            self.assertEqual(action['kind'],'speak');self.assertEqual(action['target'],'hark')
            self.assertFalse(attacking(action));self.assertEqual(action['text'],text)
        resolver.assert_not_called()

    def test_actual_attacks_remain_attacks_without_becoming_dialogue(self):
        for text in ['aim for his neck and stab him',"take out my knife and slice across Hark's neck",'我刺向他的頸部']:
            self.assertTrue(attacking(interpret(self.state,text)))

    def test_thought_does_not_produce_npc_knowledge_or_physical_effects(self):
        action=interpret(self.state,'I imagine stabbing him')
        self.assertFalse(attacking(action));self.assertEqual(action['target'],'')
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'qa.sqlite3',seed=self.state);before=engine.state()
            result=engine.submit(action,'private-thought',0)
            after=engine.state();after['revision']=before['revision']
            self.assertEqual(before,after);self.assertIn('沒有把',result['narration'])
            from kobold_rpg.portable import export_file,validate_file
            payload=validate_file(export_file(engine))
            self.assertIn('understanding',payload['journal'][0]['body'])
        with patch('kobold_rpg.model._complete',side_effect=AssertionError('no NPC reflection')):
            self.assertEqual(enrich_characters(self.state,action,'你沒有說出口。','local'),[])

    def test_mixed_touch_and_speech_are_preserved_as_distinct_verbatim_parts(self):
        text='i walk closer to him and put my hand around his shoulder, "of course i am just kidding"'
        parsed={'mode':'mixed','actions':['i walk closer to him and put my hand around his shoulder'],'speech':['of course i am just kidding'],'thoughts':[]}
        resolver=Mock(return_value=parsed)
        action=interpret(self.state,text,resolver=resolver)
        resolver.assert_not_called()
        self.assertEqual(action['text'],text);self.assertEqual(action['target'],'hark')
        self.assertEqual(action['understanding'],parsed);self.assertEqual(action['kind'],'freeform')

    def test_violent_quote_does_not_contaminate_an_ordinary_action(self):
        text='I walk closer and say "why would I kill you?"'
        parsed={'mode':'mixed','actions':['I walk closer'],'speech':['why would I kill you?'],'thoughts':[]}
        action=interpret(self.state,text,resolver=lambda _:parsed)
        self.assertFalse(attacking(action))

    def test_question_followed_by_a_real_attack_uses_semantics_not_question_shortcut(self):
        text='Why would I kill you? I stab Hark'
        parsed={'mode':'mixed','actions':['I stab Hark'],'speech':['Why would I kill you?'],'thoughts':[]}
        resolver=Mock(return_value=parsed);action=interpret(self.state,text,resolver=resolver)
        self.assertEqual(resolver.call_count,1);self.assertTrue(attacking(action))

    def test_unknown_or_invented_classification_cannot_execute_an_action(self):
        for parsed in [{'mode':'uncertain','actions':[],'speech':[],'thoughts':[]},
                       {'mode':'action','actions':['I stab Hark'],'speech':[],'thoughts':[]}]:
            with self.assertRaises(RuleError):interpret(self.state,'I do not want to hurt you',resolver=lambda _:parsed)
        with self.assertRaises(RuleError):interpret(self.state,'an ambiguous declaration')

    def test_parser_cannot_drop_or_overlap_a_second_action(self):
        text='I walk closer and stab Hark'
        for parsed in [pack('action','I walk closer'),{'mode':'mixed','actions':[text],'speech':['stab Hark'],'thoughts':[]}]:
            with self.assertRaises(RuleError):validate_understanding(text,parsed)

    def test_multiple_people_do_not_gain_an_arbitrary_addressee(self):
        self.state['npcs']['anya']['location']='gate'
        action=interpret(self.state,'Why would I kill you?')
        self.assertEqual(action['target'],'')
        self.assertEqual(check_action(self.state,action)[0],'review')

    def test_item_shortcut_does_not_turn_a_question_into_item_use(self):
        action=interpret(self.state,'Why would I stab you?',{'kind':'use_item','item':'hunting_knife'})
        self.assertEqual(action['kind'],'speak');self.assertEqual(action['item'],'')

    def test_explicit_non_action_intent_is_not_overridden_by_combat_keywords(self):
        text='I will not stab Hark'
        action=interpret(self.state,text,resolver=lambda _:pack('speech',text))
        self.assertFalse(attacking(action));self.assertEqual(action['kind'],'speak')

    def test_semantic_protocol_derives_mode_from_categories_without_copying_an_enum_template(self):
        from kobold_rpg.understanding import semantic_understanding
        with patch('kobold_rpg.model._complete',return_value={'actions':['I smile at Hark'],'speech':[],'thoughts':[]}) as model:
            result=semantic_understanding('I smile at Hark','local')
        self.assertEqual(result['mode'],'action')
        self.assertNotIn('speech|thought',model.call_args.args[0][0]['content'])
        validate_understanding('I smile at Hark',result)


if __name__=='__main__':unittest.main()
