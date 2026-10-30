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
from kobold_rpg.illustrations import IllustrationService, endpoint_url, image_bytes, translate_prompt, visual_source
from kobold_rpg.library import CampaignLibrary
from server import make_handler
from scripts.legacy_images import install, patched_server, FILES

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
                                     enricher=lambda *args: [],planner=None,gm=None)
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


class IllustrationInstallerTests(unittest.TestCase):
    def test_installation_preserves_later_context_work_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            (target / 'kobold_rpg').mkdir()
            (target / 'kobold_rpg/engine.py').write_text('# fixture')
            live = Path(__file__).resolve().parent.parent / 'server.py'
            old = live.read_text().replace('from kobold_rpg.illustrations import with_illustrations\n', '')
            old = old.replace('return with_illustrations(Handler, engine, model_url, token, library, operation_lock)', 'return Handler')
            old = old.replace('        server.RequestHandlerClass.illustrations.join()\n', '')
            old += '\n# Context fix from another task must survive the installer.\n'
            (target / 'server.py').write_text(old)
            install(target, dry_run=True)
            self.assertEqual((target / 'server.py').read_text(), old)
            self.assertFalse((target / 'illustrations.js').exists())
            install(target)
            modified = (target / 'server.py').read_text()
            self.assertIn('Context fix from another task', modified)
            self.assertIn('return with_illustrations(', modified)
            self.assertEqual(patched_server(modified), modified)
            self.assertTrue(all((target / name).is_file() for name in FILES))
            backups = list((target / 'image-update-backups').glob('*/server.py'))
            self.assertEqual(backups[0].read_text(), old)

    def test_changed_handler_structure_is_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            patched_server('from pathlib import Path\ndef make_handler():\n    return DifferentHandler\n')


if __name__ == '__main__':
    unittest.main()
