import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from kobold_rpg.engine import Engine
from kobold_rpg.campaign import new_campaign
from kobold_rpg.canon import digest
from unittest.mock import patch
from server import make_handler


class PrivateAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.engine = Engine(Path(cls.tmp.name) / 'world.sqlite3')
        action = {"kind": "speak", "target": "hark", "text": "我向哈克道謝。"}
        p = cls.engine.propose(action, {"outcome": "partial", "reason": "受到體諒。", "narration": "哈克輕聲道謝。", "events": [
            {"type": "social_experience", "npc": "hark", "subject": "ben", "observed": "班道謝。",
             "interpretation": "覺得受到重視。", "emotions": ["溫暖"],
             "changes": {"affection": {"before": None, "after": "初步享受相處，未形成浪漫承諾"}}, "recalls": []}]}, 0)
        cls.engine.approve(p['id'], 'test-private')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(cls.engine, 'http://127.0.0.1:5001', 'test-token',planner=None,gm=None))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def get(self, path, token=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('GET', path, headers={'X-RPG-Token': token} if token else {})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_player_endpoint_hides_inner_life(self):
        code, body = self.get('/api/state')
        self.assertEqual(code, 200)
        self.assertNotIn('inner_life', body['npcs']['hark'])

    def test_gm_endpoint_requires_session_token(self):
        for token in (None, 'wrong-token'):
            code, _ = self.get('/api/gm/npcs', token)
            self.assertEqual(code, 404)

    def test_gm_can_read_without_changing_world(self):
        before = self.engine.state()
        code, body = self.get('/api/gm/npcs', 'test-token')
        self.assertEqual(code, 200)
        self.assertEqual(body['npcs']['hark']['inner_life']['current_emotions'][0]['feeling'], '溫暖')
        self.assertEqual(self.engine.state(), before)


class CanonAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = Engine(Path(self.tmp.name) / 'world.sqlite3', seed=new_campaign())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.engine, 'http://127.0.0.1:5001', 'test-token',planner=None,gm=None))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.action = {'kind': 'speak', 'text': '我向哈克打招呼。', 'target': 'hark'}
        self.proposal = {'outcome': 'success', 'reason': '可以聽見問候。', 'narration': '哈克向班點頭。', 'events': []}

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self, method, path, body=None, token='test-token'):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            conn.request(method, path, body=json.dumps(body) if body is not None else None,
                         headers={'X-RPG-Token': token, 'Content-Type': 'application/json'})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_registry_is_private(self):
        self.assertEqual(self.request('GET', '/api/gm/canon', token='wrong')[0], 404)
        code, data = self.request('GET', '/api/gm/canon')
        self.assertEqual(code, 200)
        self.assertEqual(set(data['canon']['actors']), {'ben', 'hark', 'anya'})

    def test_client_supplied_audit_cannot_bypass_server_check(self):
        with patch('server.audit_narration', return_value=None):
            code, _ = self.request('POST', '/api/propose', {'action': self.action, 'proposal': self.proposal,
                'revision': 0, 'audit': {'supported': True}})
        self.assertEqual(code, 400)
        self.assertEqual(self.engine.state()['revision'], 0)

    def test_model_audit_rejection_does_not_store_proposal_or_change_world(self):
        audit = {'revision': 0, 'proposal_hash': digest(self.proposal),
                 'result': {'supported': False, 'actors': ['hark'], 'powers': [], 'issues': ['沒有依據']}}
        with patch('server.draft', return_value=self.proposal), patch('server.audit_narration', return_value=audit):
            code, _ = self.request('POST', '/api/draft', {'action': self.action, 'revision': 0})
        self.assertEqual(code, 400)
        self.assertEqual(self.engine.state()['revision'], 0)
        with self.engine.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM proposals').fetchone()[0], 0)

    def test_establishment_requires_explicit_authenticated_operation(self):
        body = {'confirmed': True, 'definition': {'kind': 'flag', 'id': 'checked', 'value': True},
                'source': '先行核實條件', 'revision': 0, 'request_id': 'establish-one'}
        self.assertEqual(self.request('POST', '/api/establish', body, token='wrong')[0], 403)
        self.assertEqual(self.engine.state()['revision'], 0)
        self.assertEqual(self.request('POST', '/api/establish', body)[0], 200)
        self.assertTrue(self.engine.state()['canon']['flags']['checked']['value'])


if __name__ == '__main__':
    unittest.main()
