"""Old Ma regressions: preserve history, answer the follow-up, retain agency."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine,RuleError
from kobold_rpg.canon import digest
from kobold_rpg.model import react
from kobold_rpg.dialogue import dialogue_context,split_stance,spoken_text,player_utterance,record_exchange,quoted_texts,history_message,repetition_issue
from kobold_rpg.portable import export_file,validate_state

OLD='老馬握著匕首說：「若是為了找同伴，最好說明對方的特徵。別讓我覺得你是來搶我這最後一點補給的，或是想把我賣給那些灰化的怪物。」'
BAD='老馬轉動匕首，苦笑：「若是為了找同伴，最好說明對方的特徵。別讓我覺得你是來搶我這最後一點補給的，或是想把我賣給那些灰化的怪物。」'
DOUBLE=BAD+'他側身，又說：「若是為了找同伴，最好說明對方的特徵。別讓我覺得你是來搶我這最後一點補給的，或是想把我賣給那些灰化的怪物。」'
GOOD='老馬握緊匕首：「因為你只說要找女人，沒說是誰。我猜不出你的意思，所以往壞處想；那是我的猜測。我現在還不信任你。」'


class DialogueProgressTests(unittest.TestCase):
    def setUp(self):
        self.state=new_campaign();npc=self.state['npcs']['hark']
        npc['name']='老馬（Old Ma）';npc['encounter']['stance']='警戒，手持匕首，等待對方說明特徵'
        self.action={'kind':'speak','target':'hark','text':'當交換條件? why would you say that?'}
        self.recent=[{'revision':1,'target':'hark','kind':'speak','declaration':'i am searching for women, do you know where i can find them.','narration':OLD}]

    def proposal(self,text):return {'outcome':'partial','reason':'解釋自己的猜測，仍然戒備。','narration':text,'events':[]}

    def test_past_current_stance_and_current_question_are_separate_without_extra_call(self):
        before=copy.deepcopy(self.state)
        with patch('kobold_rpg.model._complete',return_value=self.proposal(GOOD)) as model:
            react(self.state,self.action,recent=self.recent)
        messages=model.call_args.args[0];past=json.loads(messages[-1]['content']);now=past
        self.assertEqual([message['role'] for message in messages],['system','user','assistant','user'])
        self.assertEqual(messages[1]['content'],self.recent[0]['declaration'])
        self.assertEqual(messages[2]['content'],self.recent[0]['narration'])
        self.assertEqual(past['established_state']['npc']['current_stance'],'警戒，手持匕首')
        self.assertEqual(past['conversation_state']['previous_requests'],['等待對方說明特徵'])
        self.assertEqual(now['current_turn']['player_says'],self.action['text'])
        self.assertIn('原因追問',now['current_turn']['response_task'])
        self.assertNotIn('current_turn',past['established_state']);self.assertNotIn('past_conversation',now['current_turn'])
        self.assertNotIn('等待對方說明特徵',json.dumps(past['established_state'],ensure_ascii=False))
        self.assertEqual(model.call_count,1);self.assertEqual(self.state,before)
        schema=model.call_args.kwargs['response_schema']
        self.assertEqual(set(schema['required']),{'reason','narration','outcome','events'})
        self.assertNotIn('clarify',schema['properties']['outcome']['enum'])
        self.assertEqual(schema['properties']['events']['items']['properties']['npc']['enum'],['hark'])
        self.assertEqual(schema['properties']['events']['items']['properties']['field']['enum'],['stance'])

    def test_changed_gestures_and_same_reply_internally_repeated_are_detected(self):
        for text in (BAD,DOUBLE):
            self.assertIsNotNone(repetition_issue(self.action,self.proposal(text),self.recent))

    def test_slightly_reworded_old_request_is_still_not_a_new_answer(self):
        text=BAD.replace('最好說明對方的特徵','最好先說明對方的特徵').replace('這最後一點補給','這最後一點點補給')
        self.assertIsNotNone(repetition_issue(self.action,self.proposal(text),self.recent))

    def test_same_request_with_a_substantial_new_explanation_is_allowed(self):
        text=GOOD+'他補充：「若是為了找同伴，最好說明對方的特徵。」'
        self.assertIsNone(repetition_issue(self.action,self.proposal(text),self.recent))

    def test_a_new_explanation_cannot_hide_a_whole_replayed_old_paragraph(self):
        self.assertIsNotNone(repetition_issue(self.action,self.proposal(BAD+'\n'+GOOD),self.recent))

    def test_nested_quote_does_not_truncate_the_original_sentence(self):
        text='老馬說：「你是想把我賣給那些『灰化』的怪物嗎？」'
        self.assertEqual(quoted_texts(text),['你是想把我賣給那些『灰化』的怪物嗎？'])

    def test_known_eventless_repetition_is_recapped_without_changing_original_history(self):
        row={**self.recent[0],'revision':2,'has_events':False,'narration':DOUBLE};before=copy.deepcopy(row)
        recap=history_message(row,self.recent)
        self.assertIn('歷史紀錄摘要',recap);self.assertEqual(row,before)
        self.assertEqual(history_message({**row,'has_events':True},self.recent),DOUBLE)
        self.assertEqual(history_message({**row,'narration':GOOD},self.recent),GOOD)

    def test_a_changed_decision_or_quantity_is_never_collapsed_to_an_old_quote(self):
        for before,after in [('我願意讓你留下來一起避雨，但請你暫時不要走到我的貨架後面。','我不願意讓你留下來一起避雨，但請你暫時不要走到我的貨架後面。'),
                             ('這批水我只願意交換10枚銅幣，其他物品暫時不接受交換。','這批水我只願意交換20枚銅幣，其他物品暫時不接受交換。')]:
            recent=[{**self.recent[0],'narration':'老馬說：「'+before+'」'}]
            newer='老馬說：「'+after+'」'
            self.assertIsNone(repetition_issue(self.action,self.proposal(newer),recent))
            self.assertNotEqual(before,after)

    def test_requested_repetition_and_short_refusal_are_allowed(self):
        self.assertIsNone(repetition_issue({**self.action,'text':'repeat what you just said'},self.proposal(BAD),self.recent))
        self.assertIsNone(repetition_issue({**self.action,'text':'repeat what you just said'},self.proposal(OLD),self.recent))
        self.assertIsNone(repetition_issue(self.action,self.proposal('老馬說：「不告訴你。」'),self.recent))

    def test_repeated_dialogue_is_delivered_without_repair_or_automatic_forgiveness(self):
        before=copy.deepcopy(self.state)
        with patch('kobold_rpg.model._complete',side_effect=[self.proposal(BAD),self.proposal(GOOD)]) as model:
            result=react(self.state,self.action,recent=self.recent)
        self.assertEqual(model.call_count,1);self.assertEqual(result['narration'],BAD);self.assertEqual(self.state,before)
        with patch('kobold_rpg.model._complete',return_value=self.proposal(DOUBLE)) as model:
            result=react(self.state,self.action,recent=self.recent)
        self.assertEqual(result['narration'],DOUBLE);self.assertEqual(model.call_count,1)

    def test_dialogue_mood_cannot_overwrite_physical_condition(self):
        before=copy.deepcopy(self.state)
        bad={**self.proposal(GOOD),'events':[{'type':'npc_update','npc':'hark','field':'condition','value':'仍然戒備'}]}
        with patch('kobold_rpg.model._complete',return_value=bad) as model:
            result=react(self.state,self.action,recent=self.recent)
        self.assertEqual(model.call_count,1);self.assertEqual(result,self.proposal(GOOD));self.assertEqual(self.state,before)

    def test_malformed_model_reply_still_uses_the_normal_validation_error(self):
        with patch('kobold_rpg.model._complete',return_value=[]):
            with self.assertRaises(RuleError):react(self.state,self.action,recent=self.recent)
        with patch('kobold_rpg.model._complete',return_value={**self.proposal(GOOD),'events':None}) as model:
            self.assertEqual(react(self.state,self.action,recent=self.recent),self.proposal(GOOD))
        self.assertEqual(model.call_count,1)

    def test_only_waiting_for_verbal_answers_moves_out_of_stance(self):
        for stance in ['警戒，等待救援','不准靠近，手持匕首','等待你把刀放下','守門，等待交班','拒絕透露同伴行蹤']:
            stable,requests=split_stance(stance)
            self.assertEqual(stable,stance);self.assertEqual(requests,[])
        self.assertEqual(split_stance('guarded; waiting for you to explain your purpose'),('guarded',['waiting for you to explain your purpose']))

    def test_all_current_words_survive_multiple_quotes_and_unquoted_question(self):
        text='「當交換條件？」我問：「為甚麼這樣說？」'
        self.assertEqual(spoken_text(text),'當交換條件？\n為甚麼這樣說？')
        self.assertEqual(spoken_text('當交換條件? why would you say that?'),'當交換條件? why would you say that?')
        self.assertEqual(spoken_text('You said "women". Why would you say that?'),'You said "women". Why would you say that?')

    def test_another_npc_does_not_inherit_this_exchange(self):
        context=dialogue_context(self.state['npcs']['hark'],self.action,[{**self.recent[0],'target':'anya'}])
        self.assertEqual(context['past_conversation'],[])

    def test_followup_reference_is_an_exact_quote_not_a_manufactured_explanation(self):
        old='老馬說：「你該不會是想拿她們當交換條件吧？」他又說：「先說清楚特徵。」'
        context=dialogue_context(self.state['npcs']['hark'],self.action,[{**self.recent[0],'narration':old}])
        reference=context['current_turn']['referring_to_previous_words']
        self.assertEqual(reference['quote'],'你該不會是想拿她們當交換條件吧？')
        self.assertEqual(reference['source_revision'],1)
        later={**self.recent[0],'revision':2,'narration':'老馬說：「我還沒改變主意。」'}
        self.assertEqual(dialogue_context(self.state['npcs']['hark'],self.action,[{**self.recent[0],'narration':old},later])['current_turn']['referring_to_previous_words']['source_revision'],1)
        self.assertNotIn('referring_to_previous_words',dialogue_context(self.state['npcs']['hark'],{**self.action,'text':'早安。'},self.recent)['current_turn'])

    def test_private_thoughts_are_not_heard_or_stored_as_dialogue(self):
        action={**self.action,'text':'我心想要逃走。我問：「為甚麼這樣說？」',
            'understanding':{'mode':'mixed','actions':[],'speech':['為甚麼這樣說？'],'thoughts':['我心想要逃走。']}}
        self.assertEqual(player_utterance(action),'為甚麼這樣說？')
        with patch('kobold_rpg.model._complete',return_value=self.proposal(GOOD)) as model:react(self.state,action,recent=self.recent)
        self.assertNotIn('逃走',model.call_args.args[0][-1]['content'])
        record_exchange(self.state,action,self.proposal(GOOD),1)
        self.assertNotIn('逃走',json.dumps(self.state['npcs']['hark']['dialogue'],ensure_ascii=False))

    def test_semantic_speech_spans_keep_the_original_order(self):
        action={**self.action,'understanding':{'mode':'speech','actions':[],'speech':['why would you say that?','當交換條件?'],'thoughts':[]}}
        self.assertEqual(player_utterance(action),'當交換條件?\nwhy would you say that?')

    def test_accepted_exchange_persists_and_rewinds_with_original_history(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'test.db',seed=self.state);proposal=self.proposal(GOOD)
            audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
            candidate=engine.propose(self.action,proposal,0,audit=audit)
            self.assertNotIn('dialogue',engine.state()['npcs']['hark'])
            engine.approve(candidate['id'],'once');after=engine.state();npc=after['npcs']['hark']
            self.assertEqual(npc['encounter']['stance'],'警戒，手持匕首')
            self.assertEqual(npc['dialogue']['player_said'],self.action['text'])
            self.assertEqual(npc['dialogue']['response_as_narrated'],GOOD)
            self.assertEqual(npc['dialogue']['previous_requests'],['等待對方說明特徵'])
            self.assertEqual(npc['inner_life'],self.state['npcs']['hark']['inner_life'])
            self.assertEqual(engine.history()[0]['narration'],GOOD)
            self.assertEqual(engine.history()[0]['events'],[])
            self.assertNotIn('dialogue',engine.public_state()['npcs']['hark'])
            self.assertNotIn('dialogue',after['npcs']['anya'])
            saved=export_file(engine);validate_state(saved['state'])
            self.assertEqual(saved['state']['npcs']['hark']['dialogue'],npc['dialogue'])
            restored=dialogue_context(npc,{**self.action,'text':'你可以解釋清楚嗎？'},[])
            self.assertEqual(restored['past_conversation'][0]['narration'],GOOD)
            engine.approve(candidate['id'],'once');self.assertEqual(engine.state(),after)
            engine.rewind(0,1,'back');self.assertEqual(engine.state()['npcs']['hark'],self.state['npcs']['hark'])

    def test_invalid_imported_dialogue_record_is_rejected(self):
        self.state['npcs']['hark']['dialogue']={'revision':99}
        with self.assertRaises(RuleError):validate_state(self.state)


if __name__=='__main__':unittest.main()
