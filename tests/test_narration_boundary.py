import copy
import json
import tempfile
import unittest
from pathlib import Path
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine,RuleError,canonical
from kobold_rpg.gm import decode_reply,record_changes
from kobold_rpg.gm_context import recent_context,recalled_context
from kobold_rpg.portable import export_file,validate_file
from kobold_rpg.story_text import story_text


PROSE='「你想往哪邊去？」老麥（Old Mac）問道，手裡的繩索依舊緊繃。'
TAIL='changes":{"npcs":{"guide":{"encounter":{"priorities":{"text":"確保吊橋安全","evidence":"繩索依舊緊繃"}}}}}}'
LEAK=PROSE+'\n\n'+TAIL


class NarrationBoundaryTests(unittest.TestCase):
    def test_exact_reported_orphan_tail_is_removed_without_losing_dialogue(self):
        result=decode_reply(LEAK)
        self.assertEqual(result['narration'],PROSE)
        self.assertEqual(result['changes'],{})

    def test_polluted_valid_narration_does_not_replace_authoritative_changes(self):
        changes={'npcs':{'hark':{'encounter':{'priorities':'確保吊橋安全'}}}}
        for raw in ({'narration':LEAK,'changes':changes},json.dumps({'narration':LEAK,'changes':changes},ensure_ascii=False)):
            result=decode_reply(raw)
            self.assertEqual(result['narration'],PROSE)
            self.assertEqual(result['changes'],changes)

    def test_complete_and_truncated_plain_protocol_tails_are_hidden(self):
        for tail in ['"changes": {}','changes: {"npcs":','{"changes":{"npcs":{}}}',
                     'establish: {"people":','player_power_uses: [','story_update: {']:
            with self.subTest(tail=tail):self.assertEqual(decode_reply(PROSE+'\n\n'+tail)['narration'],PROSE)

    def test_truncated_envelope_with_complete_story_still_hides_nested_leak(self):
        raw='{"narration":'+json.dumps(LEAK,ensure_ascii=False)+',"changes":{"npcs":'
        result=decode_reply(raw)
        self.assertEqual(result['narration'],PROSE);self.assertEqual(result['changes'],{})

    def test_protocol_only_is_never_delivered_as_a_story(self):
        for raw in ['{"changes":{"npcs":{}}}','changes":{"npcs":{}}',
                    {'narration':TAIL,'changes':{}},'```json\n{"changes":{}}\n```']:
            with self.subTest(raw=raw),self.assertRaises(RuleError):decode_reply(raw)

    def test_ordinary_mentions_and_intentional_code_examples_are_unchanged(self):
        for text in ['他說：「changes 是改變的意思。」','她寫下 changes: {}，然後笑了。',
                     '工程師展示：\n```json\nchanges: {"npcs":{}}\n```\n他合上手冊。']:
            self.assertEqual(story_text(text),text)
            self.assertEqual(decode_reply(text)['narration'],text)

    def test_encounter_annotation_is_stored_as_text_without_changing_input(self):
        state=new_campaign();patch={'npcs':{'hark':{'encounter':{'priorities':{'text':'確保吊橋安全','evidence':'繩索依舊緊繃'}}}}}
        before=copy.deepcopy(patch)
        after,status=record_changes(state,patch,1,PROSE)
        self.assertEqual(status,'ready');self.assertEqual(after['npcs']['hark']['encounter']['priorities'],'確保吊橋安全')
        self.assertEqual(patch,before)

    def test_engine_storage_defends_injected_gm_adapters_and_retries(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'test.sqlite3',seed=new_campaign())
            result=engine.record_gm_reply('問路',{'narration':LEAK,'changes':{}},'turn',0)
            self.assertEqual(result['narration'],PROSE)
            self.assertEqual(engine.record_gm_reply('問路',{'narration':LEAK,'changes':{}},'turn',0)['narration'],PROSE)
            self.assertEqual(engine.history()[0]['narration'],PROSE)
            self.assertTrue(engine.verify());validate_file(export_file(engine))

    def test_old_polluted_journal_is_clean_in_context_but_remains_byte_identical(self):
        with tempfile.TemporaryDirectory() as folder:
            state=new_campaign();state['pc']['location']='gate';state['npcs']['hark']['name']='老麥（Old Mac）'
            engine=Engine(Path(folder)/'old.sqlite3',seed=state)
            with engine.connect() as db:
                engine._append(db,state,copy.deepcopy(state),'legacy',{'status':'approved',
                    'action':{'kind':'freeform','text':'問路'},'narration':LEAK,'events':[],'bookkeeping':'ready'})
            with engine.connect() as db:before=tuple(db.execute('SELECT body,hash FROM journal').fetchone())
            recent,_=recent_context(engine,engine.state())
            recalled=recalled_context(engine,engine.state(),'我再問老麥路線')
            self.assertEqual(recent[0]['narration'],PROSE)
            self.assertEqual(recalled[0]['narration'],PROSE)
            with engine.connect() as db:after=tuple(db.execute('SELECT body,hash FROM journal').fetchone())
            self.assertEqual(after,before);self.assertTrue(engine.verify())
            self.assertIn('changes',json.loads(export_file(engine)['journal'][0]['body'])['narration'])
