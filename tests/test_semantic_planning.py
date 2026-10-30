"""Production player path: semantic intent first, world validation second."""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine, RuleError, check_action
from kobold_rpg.canon import digest
from kobold_rpg.dialogue import dialogue_context
from kobold_rpg.planning import public_context, resolve_plan, semantic_action, source_units, resolve_source_plan
from server import make_handler


def plan(text, kind='travel', target='anya', destination='pier', category='actions', **extra):
    return {'mode': {'actions':'action', 'speech':'speech', 'thoughts':'thought'}[category],
            'actions': [], 'speech': [], 'thoughts': [], 'kind': kind,
            'target': target, 'destination': destination, 'ability': '', 'item': '',
            category: [text], **extra}


def source_plan(text, kind='travel', target='anya', destination='pier', category='action', **extra):
    return {'parts': {key: category for key in source_units(text)}, 'compound':False, 'kind': kind,
            'target': target, 'destination': destination, 'ability': '', 'item': '', **extra}


class SemanticPlanningTests(unittest.TestCase):
    def setUp(self):
        self.state = new_campaign()
        self.state['pc']['location'] = 'river_street'

    def test_unlisted_phrasings_use_semantic_intent_and_keep_original(self):
        for text in ('get close to anya', 'get closer to anya', 'make my way over to Anya',
                     '縮短我和安雅之間的距離。', '安雅那邊，我走過去。'):
            with self.subTest(text=text), patch('kobold_rpg.model._complete', return_value=source_plan(text)) as model:
                action = semantic_action(self.state, text, 'http://model')
            model.assert_called_once()
            self.assertEqual((action['kind'], action['destination'], action['target']), ('travel', 'pier', ''))
            self.assertEqual(action['text'], text)
            self.assertEqual(check_action(self.state, action)[0], 'review' if action.get('compound') else 'routine')
            self.assertIn('response_schema', model.call_args.kwargs)

    def test_planner_cannot_pick_a_different_destination_for_person(self):
        action = resolve_plan(self.state, '靠近安雅', plan('靠近安雅', destination='gate'))
        self.assertEqual(action['destination'], 'pier')

    def test_private_location_does_not_change_public_destination(self):
        self.state['npcs']['anya']['location'] = 'gate'
        self.state['npcs']['anya']['inner_life'] = {'secret': '不可透露的秘密'}
        context = public_context(self.state)
        self.assertEqual(context['characters']['anya']['public_destination'], 'pier')
        self.assertNotIn('不可透露', json.dumps(context, ensure_ascii=False))
        self.state['locations']['river_street']['description'] = '雨落在街道上。'
        self.state.pop('scene', None)
        context = public_context(self.state)
        self.assertNotIn('anya', context['characters'])

    def test_question_and_thought_never_authorize_a_move_or_attack(self):
        for category, text in [('speech', 'why would I kill you?'), ('speech', '如果我走去渡口呢？'),
                               ('thoughts', 'I imagine walking to Anya')]:
            with self.subTest(text=text):
                action = resolve_plan(self.state, text, plan(text, category=category))
                self.assertNotEqual(action['kind'], 'travel')
                self.assertEqual(action['destination'], '')
                self.assertEqual(action['text'], text)

    def test_single_purpose_words_are_program_owned_not_model_copies(self):
        text = 'why would I kill you?'
        action = resolve_plan(self.state, text, plan('Why would I kill you?', category='speech'))
        self.assertEqual(action['text'], text)
        self.assertEqual(action['understanding']['speech'], [text])
        self.assertEqual(action['kind'], 'speak')

    def test_redundant_mixed_label_does_not_reject_complete_single_category(self):
        text = 'get close to anya'
        action = resolve_plan(self.state, text, plan(text, mode='mixed'))
        self.assertEqual(action['understanding']['mode'], 'action')
        self.assertEqual(action['destination'], 'pier')
        with self.assertRaises(RuleError):
            resolve_plan(self.state, 'get close to anya and shout hello', plan(text, mode='mixed'))

    def test_no_mixed_rewriting_or_omission_or_unknown_id(self):
        for text, result in [('我不刺哈克，說「你好」', plan('', mode='mixed', actions=['我刺哈克'], speech=['你好'], kind='interact', target='', destination='')),
                             ('靠近安雅', plan('靠近安雅', target='new_person')),
                             ('靠近安雅', plan('靠近安雅', destination='new_world'))]:
            with self.subTest(text=text), self.assertRaises(RuleError):
                resolve_plan(self.state, text, result)

    def test_unknown_power_is_a_checked_attempt_not_a_granted_power(self):
        text = 'I cast fire magic'
        action = resolve_plan(self.state, text, plan(text, kind='cast', target='', destination=''))
        self.assertEqual(action['kind'], 'cast')
        self.assertEqual(check_action(self.state, action)[0], 'blocked')
        self.assertEqual(self.state['pc']['spells'], [])

    def test_observation_does_not_require_a_keyword_or_change_location(self):
        text = '我瞧瞧安雅目前的模樣'
        action = resolve_plan(self.state, text, plan(text, kind='observe', destination=''))
        self.assertEqual(check_action(self.state, action)[0], 'routine')
        self.assertEqual(action['kind'], 'observe')
        self.assertEqual(self.state['pc']['location'], 'river_street')

    def test_movement_within_current_place_does_not_require_a_route_to_itself(self):
        text = 'walk along this street'
        action = resolve_plan(self.state, text, plan(text, target='', destination='river_street'))
        self.assertEqual(action['kind'], 'freeform')
        self.assertEqual(check_action(self.state, action)[0], 'review')

    def test_mixed_and_multiple_actions_are_not_partially_auto_executed(self):
        text = 'I walk to Anya and say "Hello"'
        action = resolve_plan(self.state, text, plan(text, mode='mixed', actions=['I walk to Anya'], speech=['Hello']))
        self.assertEqual(action['understanding']['mode'], 'mixed')
        self.assertEqual(check_action(self.state, action)[0], 'review')
        text = 'I walk to Anya and give her my rope and say "Hello"'
        action = resolve_plan(self.state, text, plan(text, mode='mixed', actions=['I walk to Anya', 'give her my rope'], speech=['Hello']))
        self.assertEqual(action['kind'], 'freeform')
        self.assertNotEqual(check_action(self.state, action)[0], 'routine')


class SemanticPlayerAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        seed = new_campaign(); seed['pc']['location'] = 'river_street'
        self.engine = Engine(Path(self.tmp.name) / 'game.sqlite3', seed=seed)
        # No planner override: exercise the production default.
        self.handler = make_handler(self.engine, 'http://model', 'test', enricher=lambda *args: [],gm=None)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start(); self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.handler.jobs.join(); self.handler.background.join(); self.handler.illustrations.join()

    def send(self, text='make my way over to Anya', revision=0, request_id='semantic'):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            conn.request('POST', '/api/play', json.dumps({'text': text, 'revision': revision, 'request_id': request_id}),
                         {'Content-Type': 'application/json', 'X-RPG-Token': 'test'})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_move_is_understood_once_then_checked_and_committed_once(self):
        text = 'make my way over to Anya'
        with patch('kobold_rpg.model._complete', return_value=source_plan(text)) as model, \
             patch('server.react', side_effect=AssertionError('clear move needs no story call')):
            code, result = self.send(text)
            self.assertEqual(code, 200, result)
            code, retry = self.send(text)
            self.assertEqual(code, 200, retry)
        model.assert_called_once()
        self.assertEqual(self.engine.state()['pc']['location'], 'pier')
        self.assertEqual(self.engine.state()['revision'], 1)
        self.assertEqual(self.engine.history()[-1]['action']['text'], text)
        self.assertTrue(self.engine.verify())

    def test_invalid_understanding_and_stale_revision_never_write_or_narrate(self):
        before = copy.deepcopy(self.engine.state())
        with patch('kobold_rpg.model._complete', return_value={**source_plan('do not go to Anya'), 'parts':{}}) as model, \
             patch('server.react', side_effect=AssertionError('must not narrate')):
            code, _ = self.send('do not go to Anya')
            self.assertEqual(code, 400)
            code, _ = self.send(revision=99)
            self.assertEqual(code, 400)
        model.assert_called_once()
        self.assertEqual(self.engine.state(), before)

    def test_cantonese_compound_action_reaches_story_and_is_journaled_once_verbatim(self):
        self.engine.submit({'kind':'travel','text':'前往渡口','destination':'pier'},'to-anya',0)
        before=self.engine.state();text='唔同佢爭論, 收起刀, 行近佢'
        response={'outcome':'success','reason':'停止爭論並收起獵刀，在同一棚邊靠近。',
                  'narration':'你把獵刀收好，停下爭辯，朝安雅走近。她仍留意你的距離。',
                  'events':[{'type':'npc_update','npc':'anya','field':'stance','value':'看見對方收刀，仍留意彼此距離'}]}
        audit={'revision':1,'proposal_hash':digest(response),'result':{'supported':True,'actors':['ben','anya'],'powers':[],'issues':[]}}
        with patch('kobold_rpg.model._complete',return_value=source_plan(text,kind='freeform',destination='pier')) as planning, \
             patch('server.react',return_value=response) as story,patch('server.audit_narration',return_value=audit):
            code,result=self.send(text,revision=1,request_id='cantonese')
            self.assertEqual(code,200,result)
            code,retry=self.send(text,revision=1,request_id='cantonese')
            self.assertEqual(code,200,retry)
        planning.assert_called_once();story.assert_called_once()
        action=self.engine.history()[-1]['action']
        self.assertEqual(action['text'],text)
        self.assertEqual(action['understanding']['actions'],[text])
        self.assertTrue(action['compound'])
        self.assertEqual(self.engine.state()['pc']['inventory'],before['pc']['inventory'])
        self.assertEqual(self.engine.state()['pc']['location'],'pier')
        self.assertEqual(self.engine.state()['revision'],2)
        self.assertTrue(self.engine.verify())

    def test_history_witnesses_come_from_the_original_event_location(self):
        self.engine.submit({'kind':'travel','text':'前往北門','destination':'gate'}, 'to-gate', 0)
        old_action={'kind':'freeform','text':'I wait beside Hark.'}
        old={'outcome':'success','reason':'哈克繼續原來的工作。','narration':'哈克整理交班紙。','events':[]}
        audit={'revision':1,'proposal_hash':digest(old),'result':{'supported':True,'actors':['hark'],'powers':[],'issues':[]}}
        pending=self.engine.propose(old_action,old,1,audit=audit)
        self.engine.approve(pending['id'],'old-exchange')
        self.engine.submit({'kind':'travel','text':'前往河街','destination':'river_street'}, 'back-to-street', 2)
        self.engine.submit({'kind':'travel','text':'前往渡口','destination':'pier'}, 'to-pier', 3)
        text='why would I kill you?'
        reply={'outcome':'success','reason':'安雅不曾經歷北門的事。','narration':'安雅抬頭：「我沒說你會殺我。你找我有事嗎？」','events':[]}
        audit={'revision':4,'proposal_hash':digest(reply),'result':{'supported':True,'actors':['anya'],'powers':[],'issues':[]}}
        with patch('kobold_rpg.model._complete',return_value=source_plan(text,category='speech',kind='speak',target='anya',destination='')), \
             patch('server.react',return_value=reply) as react, patch('server.audit_narration',return_value=audit):
            code,result=self.send(text,revision=4)
        self.assertEqual(code,200,result)
        recent=react.call_args.kwargs['recent']
        self.assertEqual(recent[0]['witnesses'],['hark'])
        self.assertEqual(dialogue_context(self.engine.state()['npcs']['anya'],react.call_args.args[1],recent)['past_conversation'][-1]['revision'],5)
        self.assertNotIn(old['narration'],[row['narration'] for row in dialogue_context(self.engine.state()['npcs']['anya'],react.call_args.args[1],recent)['past_conversation']])
        self.assertEqual(self.engine.history()[1]['narration'],old['narration'])


if __name__ == '__main__':
    unittest.main()
