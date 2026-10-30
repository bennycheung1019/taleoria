"""A repeated guard paragraph is not a response to a new spoken explanation."""
import copy,json,unittest
from unittest.mock import patch
from kobold_rpg.campaign import new_campaign
from kobold_rpg.play import interpret
from kobold_rpg.engine import RuleError
from kobold_rpg.model import react,enrich_characters
from kobold_rpg.dialogue import spoken_text,repetition_issue,recent_turns,dialogue_context

OLD='哈克警戒地看着班，手持短劍，问道：『你想做什麼？』'
NEW='哈克（Hark）沒有放下短劍，皺眉道：「拿刀刺人也叫玩笑？先把刀收好，離我遠一點。」'


class DialogueContinuityTests(unittest.TestCase):
    def test_unaddressed_old_action_is_not_every_characters_experience(self):
        state=new_campaign();state['pc']['location']='pier'
        action={'kind':'speak','target':'anya','text':'why would I kill you?'}
        old={'revision':11,'target':'','kind':'freeform','witnesses':['hark'],
             'declaration':'aim for his neck and stab him','narration':'哈克拔出短劍。'}
        seen={'revision':12,'target':'','kind':'freeform','witnesses':['anya'],
              'declaration':'我在棚邊停下','narration':'雨點落在渡船上。'}
        recent=[old,seen];before=copy.deepcopy(recent)
        context=dialogue_context(state['npcs']['anya'],action,recent)
        self.assertEqual(context['past_conversation'],[seen])
        self.assertEqual(recent,before)
        proposal={'outcome':'success','reason':'她沒有經歷過該衝突。','narration':'安雅抬頭：「我沒說你要殺我。找我有什麼事？」','events':[]}
        with patch('kobold_rpg.model._complete',return_value=proposal) as model:
            react(state,action,recent=recent)
        messages=model.call_args.args[0]
        self.assertNotIn(old['narration'],[message['content'] for message in messages])
        self.assertIn(seen['narration'],[message['content'] for message in messages])

    def setUp(self):
        self.state=new_campaign()
        self.state['npcs']['hark']['encounter']['stance']='警戒且疑慮'
        self.state['npcs']['hark']['encounter']['condition']='已回答班的問題，現在更關心交班問題'
        self.action=interpret(self.state,r'\"i am just playing\" i said')
        self.recent=[{'declaration':'aim for his neck and stab him','narration':'哈克閃避，獵刀刺空。'},
                     {'declaration':r'\"i am just playing\"','narration':OLD}]

    def proposal(self,text):return {'outcome':'success','reason':'聽到解釋，仍不信任對方並維持距離。','narration':text,'events':[]}

    def test_quoted_or_escaped_dialogue_has_a_clean_current_utterance(self):
        for text in ['"i am just playing"',r'\"i am just playing\" i said','我說：「我只是開玩笑。」']:
            self.assertIn(spoken_text(text),['i am just playing','我只是開玩笑。'])
        self.assertEqual(self.action['kind'],'speak');self.assertEqual(self.action['target'],'hark')
        self.assertEqual(self.action['text'],r'\"i am just playing\" i said')

    def test_old_prompts_and_responses_remain_paired_and_are_not_the_current_line(self):
        self.assertEqual(recent_turns(self.recent),self.recent)
        with patch('kobold_rpg.model._complete',return_value=self.proposal(NEW)) as model:
            result=react(self.state,self.action,'http://local',recent=self.recent)
        messages=model.call_args.args[0];body=json.loads(messages[-1]['content']);turn=body
        self.assertEqual(turn['current_turn']['player_says'],'i am just playing')
        self.assertEqual([message['content'] for message in messages if message['role']=='assistant'],[row['narration'] for row in self.recent])
        self.assertNotIn('past_conversation',turn['current_turn'])
        self.assertEqual(body['established_state']['npc']['current_stance'],'警戒且疑慮')
        self.assertNotIn('appraisal',body['established_state']['npc'])
        self.assertNotIn('已回答班的問題',json.dumps(body['established_state'],ensure_ascii=False))
        self.assertNotIn('核對一張',body['established_state']['scene']['description'])
        self.assertEqual(body['established_state']['npc']['initial_visible_description'],self.state['npcs']['hark']['description'])
        self.assertEqual(model.call_count,1);self.assertEqual(result['narration'],NEW)

    def test_exact_repetition_is_returned_without_a_delivery_block_or_extra_generation(self):
        before=copy.deepcopy(self.state)
        with patch('kobold_rpg.model._complete',side_effect=[self.proposal(OLD),self.proposal(NEW)]) as model:
            result=react(self.state,self.action,'http://local',recent=self.recent)
        self.assertEqual(model.call_count,1);self.assertEqual(result['narration'],OLD);self.assertEqual(self.state,before)
        request=json.loads(model.call_args.args[0][-1]['content'])
        self.assertIsNone(request['correction_of_unapplied_draft'])

    def test_alternative_name_format_and_common_script_variants_do_not_hide_repetition(self):
        converted='哈克（Hark）警戒地看著班，手持短劍，問道：「你想做什麼？」'
        self.assertIsNotNone(repetition_issue(self.action,self.proposal(converted),self.recent))

    def test_repeated_reply_does_not_reroll_or_raise_a_quality_error(self):
        with patch('kobold_rpg.model._complete',return_value=self.proposal(OLD)) as model:
            result=react(self.state,self.action,'http://local',recent=self.recent)
        self.assertEqual(result['narration'],OLD)
        self.assertEqual(model.call_count,1);self.assertEqual(self.state['revision'],0)

    def test_suspicion_and_a_brief_repeated_refusal_remain_valid(self):
        self.assertIsNone(repetition_issue(self.action,self.proposal(NEW),self.recent))
        self.assertIsNone(repetition_issue(self.action,self.proposal('不了。'),[{'narration':'不了。'}]))
        self.assertNotIn('trust',self.proposal(NEW));self.assertEqual(self.proposal(NEW)['events'],[])

    def test_deescalation_can_be_reflected_without_automatically_restoring_trust(self):
        reflected={'emotions':['仍然戒備'],'interpretation':'聽到了玩笑的解釋，但先前的攻擊仍然令人不安。','changes':{}}
        with patch('kobold_rpg.model._complete',return_value=reflected) as model:
            events=enrich_characters(self.state,self.action,NEW,'http://local')
        self.assertEqual(model.call_count,1)
        event=next(e for e in events if e['type']=='social_experience')
        self.assertEqual(event['changes'],{});self.assertEqual(event['emotions'],['仍然戒備'])


if __name__=='__main__':unittest.main()
