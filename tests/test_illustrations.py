import base64
import copy
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine, RuleError
from kobold_rpg.illustrations import IllustrationService, endpoint_url, image_bytes, translate_prompt, visual_source, moment_prompt
from kobold_rpg.library import CampaignLibrary
from server import make_handler

PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII='


class IllustrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        seed = new_campaign()
        seed['npcs']['hark']['anchor']['concern'] = 'PRIVATE-SECRET-DO-NOT-DRAW'
        seed['npcs']['anya']['description'] = 'UNSEEN-CHARACTER-DESCRIPTION'
        self.engine = Engine(root / 'world.sqlite3', seed=seed)
        self.session = 'session-one'
        self.lock = threading.RLock()
        self.calls = []
        self.service = IllustrationService(root / 'art', lambda: self.engine, lambda: self.session,
            self.lock, 'http://127.0.0.1:5001', renderer=self.renderer,
            translator=lambda source, url: 'A rain-soaked stone gate under a warm lantern')
        self.addCleanup(self.service.join)

    def renderer(self, row):
        self.calls.append(copy.deepcopy(row))
        return PNG

    def request(self, **extra):
        return {'kind': 'scene', 'session_id': self.session, 'revision': self.engine.state()['revision'],
                'request_id': 'request-first', **extra}

    def complete(self, body=None):
        row = self.service.submit(body or self.request())
        self.service.join()
        return next(r for r in self.service.snapshot()['images'] if r['id'] == row['id'])

    def test_scene_generation_is_read_only_and_prompt_does_not_receive_private_fields(self):
        before, history = self.engine.state(), self.engine.history()
        row = self.complete()
        self.assertEqual(row['status'], 'done')
        self.assertEqual(self.engine.state(), before)
        self.assertEqual(self.engine.history(), history)
        self.assertTrue(self.engine.verify())
        serialized = json.dumps(self.calls[0]['source'])
        self.assertNotIn('PRIVATE-SECRET', serialized)
        self.assertNotIn('UNSEEN-CHARACTER', serialized)
        self.assertNotIn('inner_life', serialized)
        self.assertEqual(self.service.image(row['id']), base64.b64decode(PNG))

    def test_historical_moment_draws_its_saved_story_not_the_current_scene(self):
        self.engine.record_gm_reply('我伸手接住燈籠。', {'narration':'哈克（Hark）遞給你一盞紅色燈籠。', 'changes':{}}, 'moment-one', 0)
        self.engine.record_gm_reply('我走開。', {'narration':'你在雨中向前走。', 'changes':{}}, 'moment-two', 1)
        before, history = self.engine.state(), self.engine.history()
        row = self.complete(self.request(kind='moment', subject='1'))
        self.assertEqual(row['status'], 'done')
        source = self.calls[0]['source']
        self.assertEqual(source['narration'], '哈克（Hark）遞給你一盞紅色燈籠。')
        self.assertEqual(source['action'], '我伸手接住燈籠。')
        self.assertNotIn('你在雨中向前走', json.dumps(source, ensure_ascii=False))
        self.assertNotIn('PRIVATE-SECRET', json.dumps(source))
        self.assertNotIn('UNSEEN-CHARACTER', json.dumps(source))
        self.assertEqual(row['revision'], 1)
        self.assertEqual(len(self.service.snapshot()['moments']), 2)
        self.assertEqual(self.engine.state(), before)
        self.assertEqual(self.engine.history(), history)
        again = self.service.submit(self.request(kind='moment', subject='1', request_id='moment-cache'))
        self.assertEqual(again['id'], row['id'])
        self.assertTrue(self.engine.verify())

    def test_moment_rejects_future_missing_and_client_supplied_story(self):
        for subject in ('1', '0', '-1', '../1', [], None):
            with self.subTest(subject=subject), self.assertRaises(RuleError):
                self.service.submit(self.request(kind='moment', subject=subject, narration='invented'))
        self.assertEqual(self.calls, [])

    def test_moment_renderer_uses_landscape_and_final_narration(self):
        self.engine.record_gm_reply('我試著飛。', {'narration':'你仍站在地上。', 'changes':{}}, 'moment-one', 0)
        row = self.complete(self.request(kind='moment', subject='1'))
        self.assertEqual(row['status'], 'done')
        self.assertIn('narrative scene', self.calls[0]['prompt'])
        with patch('kobold_rpg.illustrations.http_json', return_value={'images':[PNG]}) as call:
            self.service._render(self.calls[0])
        self.assertEqual((call.call_args.args[1]['width'], call.call_args.args[1]['height']), (1024,768))

    def test_inspected_rock_uses_a_single_subject_closeup_instead_of_location_inventory(self):
        source={'location':{'name':'礦坑','description':'峽谷、吊橋、礦車、帳篷。'},
                'action':'我仔細看看岩石。','narration':'石面上有三道淺淺的凹痕。',
                'characters':[{'name':'老麥','description':'礦工'}]}
        plan={'scene':'Three shallow grooves mark the rough rock surface directly in front of the player.',
              'framing':'close_up'}
        with patch('kobold_rpg.model._complete',return_value=plan) as model:
            translated=translate_prompt(source,'http://model')
        prompt=translated['prompt'];self.assertEqual(translated['framing'],'close_up')
        model.assert_called_once()
        self.assertTrue(prompt.startswith('Three shallow grooves'))
        self.assertIn('fills frame',prompt)
        self.assertNotIn('mine',prompt);self.assertNotIn('miner',prompt)
        messages=model.call_args.args[0]
        self.assertEqual(next(iter(json.loads(messages[1]['content']))),'action')
        self.assertIn('only an attempt',messages[0]['content'])
        self.assertEqual(json.loads(messages[1]['content'])['place'],'礦坑')
        self.assertNotIn('峽谷',messages[1]['content'])
        self.assertEqual(model.call_args.kwargs['response_schema']['properties']['framing']['enum'],['close_up','medium','wide'])

    def test_focus_supports_conversation_and_landscape_without_forcing_closeup(self):
        scene='A traveler speaks with the woman beside the narrow riverside path.'
        for framing,expected in [('medium','medium shot'),('wide','wide view')]:
            prompt=moment_prompt({'scene':scene,'framing':framing})
            self.assertTrue(prompt.startswith(scene));self.assertIn(expected,prompt)
            self.assertNotIn('tight close-up',prompt)

    def test_incomplete_or_unsupported_focus_plan_does_not_silently_become_a_wide_view(self):
        for plan in ({'prompt':'A mine'}, {'scene':'medium','framing':'medium'},
                     {'scene':'A clear picture of the object in the scene.','framing':'macro'},
                     {'scene':'<think>hidden object in the story scene.','framing':'close_up'}):
            with self.subTest(plan=plan),self.assertRaises(RuleError):moment_prompt(plan)

    def test_custom_moment_prompt_keeps_its_selected_framing_without_a_wide_suffix(self):
        self.engine.record_gm_reply('看岩石',{'narration':'你看見石面有三道凹痕。','changes':{}},'rock',0)
        self.service.translate=lambda *args:self.fail('custom prompt must skip LLM')
        self.complete(self.request(kind='moment',subject='1',prompt='Extreme close-up of a rough rock surface'))
        self.assertTrue(self.calls[0]['prompt'].startswith('Extreme close-up'))
        self.assertNotIn('wide view',self.calls[0]['prompt'])

    def test_moment_translation_excludes_later_picnic_activity(self):
        source={'action':'我用摺疊野餐墊蓋住她。',
                'narration':'你把墊子覆蓋在阿美肩上。\n\n她從墊邊探出頭來。\n\n大家開始享用野餐。',
                'location':{'name':'河畔渡口','description':'幾位居民圍坐吃東西。'}}
        plan={'scene':'A person drapes the unfolded picnic mat over the woman while her head peeks out.',
              'framing':'medium'}
        with patch('kobold_rpg.model._complete',return_value=plan) as model:
            translated=translate_prompt(source,'http://model')
        self.assertIn('mat over the woman',translated['prompt'])
        self.assertNotIn('大家開始享用',model.call_args.args[0][1]['content'])
        self.assertNotIn('居民圍坐',model.call_args.args[0][1]['content'])
        self.assertIn('medium shot',translated['prompt'])

    def test_closeup_framing_reaches_renderer_without_a_wide_scene_suffix(self):
        self.engine.record_gm_reply('看碎石',{'narration':'碎石卡在木樑縫隙裡。','changes':{}},'rock',0)
        self.service.translate=lambda *args:{'prompt':'Close-up of small wedge-shaped rocks, lodged between wooden beams','framing':'close_up'}
        self.complete(self.request(kind='moment',subject='1'))
        row=self.calls[0]
        self.assertEqual(row['framing'],'close_up');self.assertIn('detail study',row['prompt'])
        self.assertNotIn('narrative scene illustration',row['prompt'])
        with patch('kobold_rpg.illustrations.http_json',return_value={'images':[PNG]}) as call:self.service._render(row)
        payload=call.call_args.args[1]
        self.assertEqual((payload['width'],payload['height']),(768,768))
        self.assertIn('panorama',payload['negative_prompt'])

    def test_unseen_character_is_not_eligible_for_portrait(self):
        with self.assertRaises(RuleError):
            self.service.submit(self.request(kind='portrait', subject='anya'))
        public = self.engine.public_state()
        self.assertEqual(visual_source(public, 'portrait', 'hark')['source']['name'], '哈克（Hark）')

    def test_manual_prompt_skips_language_model(self):
        self.service.translate = lambda *args: self.fail('must not call LLM')
        self.complete(self.request(prompt='A medieval rain-soaked stone gate'))
        self.assertTrue(self.calls[0]['prompt'].startswith('A medieval rain-soaked stone gate'))

    def test_owned_item_generation_is_read_only_and_uses_only_visible_description(self):
        before, history = self.engine.state(), self.engine.history()
        row = self.complete(self.request(kind='item', subject='hunting_knife'))
        self.assertEqual(row['status'], 'done')
        self.assertEqual(row['kind'], 'item')
        self.assertIn('single inventory object', self.calls[0]['prompt'])
        self.assertNotIn('single character', self.calls[0]['prompt'])
        self.assertEqual(set(self.calls[0]['source']), {'name', 'description', 'genre'})
        self.assertEqual(self.engine.state(), before)
        self.assertEqual(self.engine.history(), history)
        self.assertTrue(any(item['id'] == 'hunting_knife' for item in self.service.snapshot()['items']))

    def test_unowned_item_and_unknown_kind_cannot_generate(self):
        for subject in ('unknown_secret_artifact', [], None):
            with self.subTest(subject=subject), self.assertRaises(RuleError):
                self.service.submit(self.request(kind='item', subject=subject))
        with self.assertRaises(RuleError):
            self.service.submit(self.request(kind='spell', subject='fireball'))
        self.assertEqual(self.calls, [])

    def test_item_cache_ignores_quantity_but_changes_when_visible_appearance_changes(self):
        public = self.engine.public_state()
        initial = visual_source(public, 'item', 'hunting_knife')
        public['pc']['inventory']['hunting_knife'] = 2
        self.assertEqual(visual_source(public, 'item', 'hunting_knife')['fingerprint'], initial['fingerprint'])
        public.setdefault('item_catalog', {})['hunting_knife'] = {'name':'獵刀', 'description':'帶裂紋的刀柄', 'secret':'DO-NOT-DRAW'}
        updated = visual_source(public, 'item', 'hunting_knife')
        self.assertNotEqual(updated['fingerprint'], initial['fingerprint'])
        self.assertNotIn('secret', updated['source'])
        public['pc']['inventory']['hunting_knife'] = 0
        with self.assertRaises(RuleError): visual_source(public, 'item', 'hunting_knife')

    def test_item_renderer_uses_square_image(self):
        row = {**visual_source(self.engine.public_state(), 'item', 'hunting_knife'), 'settings':self.service.settings(), 'prompt':'An ordinary hunting knife'}
        with patch('kobold_rpg.illustrations.http_json', return_value={'images':[PNG]}) as call:
            self.service._render(row)
        self.assertEqual((call.call_args.args[1]['width'], call.call_args.args[1]['height']), (768, 768))

    def test_retry_and_cache_do_not_generate_twice_but_style_change_invalidates_cache(self):
        first = self.complete()
        self.assertEqual(self.service.submit(self.request())['id'], first['id'])
        self.assertEqual(self.service.submit(self.request(request_id='request-second'))['id'], first['id'])
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(RuleError):
            self.service.submit(self.request(prompt='different prompt'))
        self.service.configure({'style': 'ink illustration'})
        self.complete(self.request(request_id='request-third'))
        self.assertEqual(len(self.calls), 2)

    def test_restart_preserves_finished_images(self):
        first = self.complete()
        restarted = IllustrationService(self.service.root, lambda: self.engine, lambda: self.session,
                                        self.lock, 'http://127.0.0.1:5001')
        self.assertEqual(restarted.snapshot()['images'][0]['id'], first['id'])
        self.assertEqual(restarted.image(first['id']), base64.b64decode(PNG))

    def test_stale_session_and_revision_are_rejected(self):
        for extra in ({'session_id': 'old-session'}, {'revision': 99}):
            with self.assertRaises(RuleError):
                self.service.submit(self.request(**extra))

    def test_scene_switch_before_worker_starts_cancels_old_job(self):
        # Hold the same lock used by story work until selection has changed.
        with self.lock:
            row = self.service.submit(self.request())
            self.session = 'new-session'
        self.service.join()
        result = next(r for r in self.service.snapshot()['images'] if r['id'] == row['id'])
        self.assertEqual(result['status'], 'error')
        self.assertEqual(self.calls, [])

    def test_image_work_serializes_with_story_work_while_status_remains_readable(self):
        entered, release = threading.Event(), threading.Event()
        def slow(row):
            entered.set()
            release.wait(3)
            return PNG
        self.service.render = slow
        self.service.submit(self.request())
        self.assertTrue(entered.wait(2))
        self.assertEqual(self.service.snapshot()['images'][0]['status'], 'generating')
        self.assertFalse(self.lock.acquire(blocking=False))
        release.set()
        self.service.join()
        self.assertTrue(self.lock.acquire(blocking=False))
        self.lock.release()

    def test_invalid_image_fails_without_changing_story(self):
        self.service.render = lambda row: base64.b64encode(b'<html>not an image</html>').decode()
        before = self.engine.state()
        result = self.complete()
        self.assertEqual(result['status'], 'error')
        self.assertEqual(self.engine.state(), before)
        self.assertFalse(list(self.service.root.glob('*.png')))

    def test_other_campaign_cannot_read_images(self):
        row = self.complete()
        other = new_campaign()
        other['campaign_id'] = 'other-campaign'
        self.engine = Engine(Path(self.tmp.name) / 'other.sqlite3', seed=other)
        self.assertEqual(self.service.snapshot()['images'], [])
        with self.assertRaises(RuleError):
            self.service.image(row['id'])

    def test_incomplete_job_is_marked_failed_after_restart(self):
        with self.lock:
            row = self.service.submit(self.request())
            self.session = 'changed'
        self.service.join()
        saved = self.service._rows()[0]
        saved['status'] = 'generating'
        self.service._save(saved)
        restarted = IllustrationService(self.service.root, lambda: self.engine, lambda: self.session,
                                         self.lock, 'http://127.0.0.1:5001')
        self.assertEqual(restarted.snapshot()['images'][0]['status'], 'error')

    def test_translation_uses_isolated_json_messages(self):
        source = visual_source(self.engine.public_state(), 'scene')['source']
        with patch('kobold_rpg.model._complete', return_value={'prompt': 'Rain on a stone gate'}) as complete:
            self.assertEqual(translate_prompt(source, 'http://127.0.0.1:5001'), 'Rain on a stone gate')
        messages = complete.call_args.args[0]
        self.assertEqual(len(messages), 2)
        self.assertNotIn('PRIVATE-SECRET', json.dumps(messages))
        self.assertEqual(complete.call_args.kwargs['response_schema']['required'], ['prompt'])

    def test_drawthings_http_payload_has_lightning_settings(self):
        row = {**visual_source(self.engine.public_state(), 'scene'), 'settings': self.service.settings(), 'prompt': 'A stone gate'}
        with patch('kobold_rpg.illustrations.http_json', return_value={'images': [PNG]}) as call:
            self.assertEqual(self.service._render(row), PNG)
        url, payload = call.call_args.args
        self.assertEqual(url, 'http://127.0.0.1:7860/sdapi/v1/txt2img')
        self.assertEqual((payload['steps'], payload['cfg_scale'], payload['batch_size']), (4, 2.0, 1))
        self.assertEqual((payload['width'], payload['height']), (1024, 768))
        self.assertFalse(payload['enable_hr'])

    def test_remote_urls_and_path_traversal_are_rejected(self):
        for url in ['https://127.0.0.1:7860', 'http://example.com', 'http://localhost@evil.com',
                    'http://localhost:7860/path', 'http://localhost:bad', 'file:///tmp/x']:
            with self.assertRaises(RuleError):
                endpoint_url(url)
        with self.assertRaises(RuleError):
            self.service.image('../../world.sqlite3')
        with self.assertRaises(RuleError):
            image_bytes('data:image/svg+xml;base64,' + PNG)


class IllustrationHandlerTests(unittest.TestCase):
    """Exercise actual HTTP parsing without network access or live game mutations."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = Engine(Path(self.tmp.name) / 'world.sqlite3', seed=new_campaign())
        self.library = CampaignLibrary(Path(self.tmp.name) / 'library', self.engine)
        self.handler = make_handler(self.engine, 'http://127.0.0.1:5001', 'test-token', self.library,
                                     )
        self.service = self.handler.illustrations
        self.service.render = lambda row: PNG
        self.service.translate = lambda *args: 'A rain-soaked stone gate'
        self.addCleanup(self.service.join)

    def request(self, method, path, body=None, token='test-token', session=None):
        data = b'' if body is None else json.dumps({'session_id': self.library.session_id, **body}).encode()
        lines = [f'{method} {path} HTTP/1.1', 'Host: localhost', f'X-RPG-Token: {token}',
                 'X-RPG-Session: ' + (session or self.library.session_id), f'Content-Length: {len(data)}',
                 'Content-Type: application/json', 'Connection: close', '', '']
        class Socket:
            def __init__(self): self.output = io.BytesIO()
            def makefile(self, mode, *args): return io.BytesIO('\r\n'.join(lines).encode() + data)
            def sendall(self, data): self.output.write(data)
        sock = Socket()
        self.handler(sock, ('127.0.0.1', 1234), None)
        head, result = sock.output.getvalue().split(b'\r\n\r\n', 1)
        status = int(head.split()[1])
        return status, result, head

    def test_snapshot_and_generation_have_real_authenticated_routes(self):
        code, raw, _ = self.request('GET', '/api/illustrations')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)['characters'][0]['id'], 'ben')
        before = self.engine.state()
        code, raw, _ = self.request('POST', '/api/illustrations/generate',
            {'kind': 'scene', 'revision': 0, 'request_id': 'api-image-first'})
        self.assertEqual(code, 202)
        key = json.loads(raw)['id']
        self.service.join()
        code, raw, header = self.request('GET', '/api/illustrations/image/' + key)
        self.assertEqual(code, 200)
        self.assertIn(b'image/png', header)
        self.assertEqual(raw, base64.b64decode(PNG))
        self.assertEqual(self.engine.state(), before)

    def test_auth_and_stale_session_and_malformed_requests(self):
        self.assertEqual(self.request('GET', '/api/illustrations', token='wrong')[0], 403)
        self.assertEqual(self.request('GET', '/api/illustrations', session='stale')[0], 400)
        self.assertEqual(self.request('POST', '/api/illustrations/generate', {'session_id': 'stale'})[0], 400)
        self.assertEqual(self.request('POST', '/api/illustrations/settings', {'endpoint': 'http://remote.example'})[0], 400)

    def test_item_generation_route_preserves_inventory_and_rejects_unowned_subject(self):
        before, history = self.engine.state(), self.engine.history()
        code, raw, _ = self.request('POST', '/api/illustrations/generate',
            {'kind':'item', 'subject':'hunting_knife', 'revision':0, 'request_id':'api-item-first'})
        self.assertEqual(code, 202)
        row = json.loads(raw)
        self.service.join()
        self.assertEqual(self.request('GET', '/api/illustrations/image/' + row['id'])[0], 200)
        self.assertEqual(self.request('POST', '/api/illustrations/generate',
            {'kind':'item', 'subject':'unowned-artifact', 'revision':0, 'request_id':'api-item-secret'})[0], 400)
        self.assertEqual(self.engine.state(), before)
        self.assertEqual(self.engine.history(), history)

    def test_existing_home_includes_assets_without_modifying_original_template(self):
        code, html, _ = self.request('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn(b'/illustrations.js', html)
        self.assertIn(b'/illustrations.css', html)
        self.assertNotIn(b'__SESSION_TOKEN__', html)
        for asset in ['/illustrations.js', '/illustrations.css']:
            self.assertEqual(self.request('GET', asset)[0], 200)

    def test_connection_failure_is_recoverable(self):
        with patch('kobold_rpg.illustrations.http_json', side_effect=OSError('offline')):
            code, raw, _ = self.request('GET', '/api/illustrations/connection')
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(raw)['connected'])


if __name__ == '__main__':
    unittest.main()
