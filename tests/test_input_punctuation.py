import copy
import unittest
from unittest.mock import Mock
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import RuleError,normalize_action
from kobold_rpg.play import interpret
from kobold_rpg.physical import attacking
from kobold_rpg.understanding import fast_understanding,validate_understanding,pack


class InputPunctuationTests(unittest.TestCase):
    def setUp(self):self.state=new_campaign()

    def test_clear_short_questions_need_no_model_and_keep_the_original(self):
        resolver=Mock(side_effect=AssertionError('clear short question needs no model'))
        for text in ['當交換條件?','當交換條件？','當交換條件?!','真的？','認真?','你的意思是交易？',
                     '那是甚麼？','什麼意思?','為甚麼？','有人嗎？','你呢?','A deal?','Really?','What for?','Why?']:
            with self.subTest(text=text):
                action=interpret(self.state,text,resolver=resolver)
                self.assertEqual(action['kind'],'speak');self.assertEqual(action['target'],'hark')
                self.assertEqual(action['text'],text);self.assertEqual(action['understanding'],pack('speech',text))
                self.assertFalse(attacking(action))
        resolver.assert_not_called()

    def test_fast_questions_cannot_hide_a_following_action_or_private_thought(self):
        for text in ['當交換條件? I stab Hark','當交換條件，我刺向哈克？','真的，I stab Hark?',
                     '什麼意思，我刺向哈克','Why, I stab Hark','Really, I imagine stabbing him?']:
            with self.subTest(text=text):self.assertIsNone(fast_understanding(text))

    def test_actual_actions_and_thoughts_do_not_become_short_questions(self):
        for text in ['I stab Hark?','我刺向哈克？','我走近他？']:
            parsed=fast_understanding(text)
            self.assertTrue(parsed is None or parsed['mode']=='action')
        self.assertEqual(fast_understanding('我心想當交換條件？')['mode'],'thought')
        self.assertIsNone(fast_understanding('當交換條件'))

    def test_equivalent_punctuation_restores_exact_original_without_mutating_model_data(self):
        for text,model_text in [('當交換條件?','當交換條件？'),('當交換條件？','當交換條件?'),
            ('請再解釋，當交換條件?','請再解釋,當交換條件？'),
            ('“不用了！”','"不用了!"'),('「不，別動手。」','"不,別動手."'),
            ('（真的嗎？）','(真的嗎?)'),("Don't do that!",'Don’t do that！')]:
            with self.subTest(text=text):
                proposed=pack('speech',model_text);before=copy.deepcopy(proposed)
                parsed=validate_understanding(text,proposed)
                self.assertEqual(proposed,before);self.assertEqual(parsed,pack('speech',text))
                self.assertEqual(validate_understanding(text,parsed),parsed)

    def test_fallback_pipeline_and_action_normalization_keep_original_spans(self):
        text='請再解釋，當交換條件?'
        resolver=Mock(return_value=pack('speech','請再解釋,當交換條件？'))
        action=interpret(self.state,text,resolver=resolver)
        resolver.assert_called_once_with(text)
        self.assertEqual(action['text'],text);self.assertEqual(action['understanding']['speech'],[text])
        normalized=normalize_action({**action,'understanding':pack('speech','請再解釋,當交換條件？')})
        self.assertEqual(normalized['understanding']['speech'],[text]);self.assertEqual(normalized['text'],text)

    def test_mixed_action_and_speech_use_their_original_nonoverlapping_slices(self):
        text='I walk closer, "Hello!"'
        parsed=validate_understanding(text,{'mode':'mixed','actions':['I walk closer，'],'speech':['Hello！'],'thoughts':[]})
        self.assertEqual(parsed['actions'],['I walk closer,']);self.assertEqual(parsed['speech'],['Hello!'])
        with self.assertRaises(RuleError):validate_understanding('當交換條件?',{'mode':'mixed','actions':['當交換條件?'],'speech':['當交換條件？'],'thoughts':[]})

    def test_words_negation_names_numbers_and_meaningful_separators_stay_strict(self):
        cases=[('當交換條件?','你是說當交換條件嗎？'),('我不殺他。','我殺他。'),
               ('I do not stab Hark!','I stab Hark！'),('I stab Hark.','I stab Mark。'),
               ('I wait 10 seconds.','I wait 20 seconds。'),('不，殺他。','不殺他。'),
               ('不殺他。','不，殺他。'),('Really?','Really!'),('No; stop.','No, stop。'),
               ('I wait -3 hours.','I wait 3 hours。'),('I wait 3.5 hours.','I wait 3。5 hours。'),
               ('I stab Hark.','Ｉ stab Hark。'),('I stab Hark.','i stab Hark。'),
               ('I do not stab Hark.','I do not  stab Hark。')]
        for text,model_text in cases:
            with self.subTest(text=text,model_text=model_text):
                with self.assertRaises(RuleError):validate_understanding(text,pack('action',model_text))

    def test_equivalent_punctuation_does_not_make_dropping_an_action_valid(self):
        text='I walk closer, then stab Hark.'
        with self.assertRaises(RuleError):validate_understanding(text,pack('action','I walk closer，'))

    def test_single_purpose_input_keeps_every_original_word_and_action_order(self):
        text='I am not going to harm you.'
        self.assertEqual(validate_understanding(text,pack('speech','am not going to harm you。')),pack('speech',text))
        text='I draw my knife and stab Hark'
        parsed={'mode':'action','actions':['stab Hark','I draw my knife'],'speech':[],'thoughts':[]}
        self.assertEqual(validate_understanding(text,parsed),pack('action',text))

    def test_mixed_parts_are_restored_in_source_order_not_model_order(self):
        text='I draw my knife, "Stop!", then stab Hark'
        parsed={'mode':'mixed','actions':['stab Hark','I draw my knife，'],'speech':['Stop！'],'thoughts':[]}
        restored=validate_understanding(text,parsed)
        self.assertEqual(restored['actions'],['I draw my knife,','stab Hark'])
        self.assertEqual(restored['speech'],['Stop!'])

    def test_unknown_inputs_still_use_validated_semantics_instead_of_assuming_speech(self):
        text='an ambiguous declaration'
        resolver=Mock(return_value=pack('action','an entirely different action'))
        with self.assertRaises(RuleError):interpret(self.state,text,resolver=resolver)
        resolver.assert_called_once_with(text)


if __name__=='__main__':unittest.main()
