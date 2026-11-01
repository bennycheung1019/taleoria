"""Named local saves and isolated campaigns, using complete SQLite backups."""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone
from .engine import Engine, RuleError
from .worldgen import build_world
from .player_view import encounters
from .portable import validate_file,validate_state


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    os.replace(temporary, path)


class CampaignLibrary:
    def __init__(self, root, initial_engine):
        self.root = Path(root).resolve()
        for folder in (self.root, self.root / 'campaigns', self.root / 'saves'):
            folder.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.selection_lock = threading.RLock()
        self.initial_path = initial_engine.path.resolve()
        self.engine = initial_engine
        self.session_id = secrets.token_urlsafe(18)
        self.previews = {}
        self.index_path = self.root / 'index.json'
        self.pointer_path = self.root / 'active.json'
        self.creation_history_path = self.root / 'creation_history.json'
        self.index = json.loads(self.index_path.read_text()) if self.index_path.exists() else {'campaigns': {}, 'saves': {}}
        # Disk paths travel with the library; callers still use absolute paths.
        for group in ('campaigns', 'saves'):
            for row in self.index[group].values():
                path = Path(row['path'])
                row['path'] = str((self.root / path).resolve() if not path.is_absolute() else path.resolve())
        self._index_campaign(initial_engine)
        if self.pointer_path.exists():
            pointer = json.loads(self.pointer_path.read_text())
            key = pointer.get('campaign')
            if key in self.index['campaigns']:
                self.engine = self._campaign(key)
        self._persist()

    def _index_campaign(self, engine):
        if engine.state().get('setup_required'):return None
        # A file key identifies a branch. campaign_id alone does not distinguish saves.
        path = engine.path.resolve()
        key = next((k for k, v in self.index['campaigns'].items() if v['path'] == str(path)), None)
        if key is None:
            key = uuid.uuid4().hex
        self.index['campaigns'][key] = self._metadata(engine, str(path))
        return key

    def _metadata(self, engine, path):
        state = engine.state()
        history = engine.history()
        timestamp = history[-1]['at'] if history else datetime.fromtimestamp(engine.path.stat().st_mtime, timezone.utc).isoformat()
        return {'path': path, 'title': state['contract'].get('title', '未命名戰役'),
                'player': state['pc']['name'], 'location': state['locations'][state['pc']['location']]['name'],
                'revision': state['revision'], 'updated_at': timestamp, 'campaign_id': state['campaign_id']}

    def _allowed(self, path):
        path = Path(path).resolve()
        if path != self.initial_path and not path.is_relative_to(self.root):
            raise RuleError('存檔不在本機遊戲資料夾內。')
        if not path.is_file():
            raise RuleError('找不到這份存檔。')
        return path

    def _campaign(self, key):
        if key not in self.index['campaigns']:
            raise RuleError('找不到這個戰役。')
        engine = Engine(self._allowed(self.index['campaigns'][key]['path']))
        engine.verify()
        return engine

    def _persist(self):
        portable = {group: {key: {**row, 'path': Path(os.path.relpath(row['path'], self.root)).as_posix()}
                            for key, row in self.index[group].items()}
                    for group in ('campaigns', 'saves')}
        atomic_json(self.index_path, portable)

    def _activate(self, engine, key):
        engine.verify()
        # Persist selection before publishing the new active reference.
        self._persist()
        atomic_json(self.pointer_path, {'campaign': key})
        with self.selection_lock:
            self.engine = engine
            self.session_id = secrets.token_urlsafe(18)
        return {'session_id': self.session_id, 'campaign_id': engine.state()['campaign_id']}

    def public_state(self):
        with self.selection_lock:
            engine, session_id = self.engine, self.session_id
        return {**engine.public_state(), 'session_id': session_id}

    def session_snapshot(self):
        with self.selection_lock:
            engine, session_id = self.engine, self.session_id
        with engine.connect() as db:
            db.execute('BEGIN')
            state = json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
            history=[]
            for r in db.execute('SELECT revision,body,before_state,after_state FROM journal ORDER BY revision'):
                before=json.loads(r['before_state']);after=json.loads(r['after_state'])
                history.append({'revision':r['revision'],**json.loads(r['body']),
                    '_encounters':encounters(before)+encounters(after),
                    '_visited':[before['pc']['location'],after['pc']['location']], '_origin':before['pc']['location']})
        return {**engine.public_state(state, history), 'session_id': session_id}, history

    def import_file(self, payload):
        with self.lock:
            try:
                payload=validate_file(payload)
            except (ValueError,TypeError,KeyError,AttributeError) as exc:
                raise RuleError(str(exc) if isinstance(exc,RuleError) else '存檔資料不正確，目前冒險沒有改動。') from exc
            path=self.root/'campaigns'/(uuid.uuid4().hex+'.sqlite3')
            try:
                engine=Engine(path,seed=payload['state'])
                with engine.connect() as db:
                    for row in payload['journal']:
                        db.execute('INSERT INTO journal(revision,request_id,body,before_state,after_state,previous_hash,hash) VALUES(?,?,?,?,?,?,?)',
                            tuple(row[k] for k in ('revision','request_id','body','before_state','after_state','previous_hash','hash')))
                engine.verify()
                key=self._index_campaign(engine)
                return self._activate(engine,key)
            except Exception:
                path.unlink(missing_ok=True)
                raise

    def check_session(self, value):
        if value != self.session_id:
            raise RuleError('遊戲連線或戰役已更新，請重新整理頁面後繼續。')

    def list(self):
        with self.lock:
            self._index_campaign(self.engine)
            self._persist()
            return {group: [{'id': k, 'active': group == 'campaigns' and Path(row['path']).resolve() == self.engine.path.resolve(),
                             **{f: v for f, v in row.items() if f != 'path'}}
                            for k, row in reversed(list(self.index[group].items()))]
                    for group in ('campaigns', 'saves')}

    @staticmethod
    def _world_summary(state, opening=''):
        return {'campaign_id': state['campaign_id'],
                'title': state['contract'].get('title', ''),
                'background': state.get('world', {}).get('background', ''),
                'location': state['locations']['start']['name'] + '：' + state['locations']['start']['description'],
                'npc': next((person['name'] + '：' + person.get('description', '')
                             for person in state.get('npcs', {}).values()), ''),
                'opening': opening,
                'entry_frame': state.get('world', {}).get('entry_frame', ''),
                'entry_setting': state.get('world', {}).get('entry_setting', '')}

    def recent_worlds(self, limit=6):
        """Small prior-opening references; no live campaign is changed."""
        with self.lock:
            rows = []
            if self.creation_history_path.exists():
                stored = json.loads(self.creation_history_path.read_text())
                if isinstance(stored, list):
                    rows.extend(reversed(stored))
            seen = {row.get('campaign_id') for row in rows}
            for key in reversed(list(self.index['campaigns'])):
                if len(rows) >= limit:
                    break
                try:
                    state = self._campaign(key).state()
                except (RuleError, OSError):
                    continue
                if state.get('world', {}).get('background') and state['campaign_id'] not in seen:
                    rows.append(self._world_summary(state))
                    seen.add(state['campaign_id'])
            return rows[:limit]

    def preview(self, candidate):
        with self.lock:
            from .npc_visibility import public_plan
            key = uuid.uuid4().hex
            if len(self.previews) >= 8:
                self.previews.pop(next(iter(self.previews)))
            self.previews[key] = candidate
            return {'preview_id': key, 'plan': public_plan(candidate['plan'], candidate['seed']),
                    'preferences': candidate['preferences']}

    def create(self, preview_id):
        with self.lock:
            candidate = self.previews.get(preview_id)
            if candidate is None:
                raise RuleError('這份世界草案已失效，請重新生成。')
            build_world(candidate['plan'], candidate['preferences'])
            validate_state(candidate['seed'])
            path = self.root / 'campaigns' / (preview_id + '.sqlite3')
            engine = Engine(path, seed=candidate['seed'])
            if engine.state()['revision'] == 0:
                from .npc_visibility import opening_for_player
                engine.record_gm_reply('【新世界開場】',{'narration':opening_for_player(candidate['plan'],candidate['seed']),
                                                       'changes':{}},'world-opening-'+preview_id,0)
            key = self._index_campaign(engine)
            prior = json.loads(self.creation_history_path.read_text()) if self.creation_history_path.exists() else []
            if not any(row.get('campaign_id') == candidate['seed']['campaign_id'] for row in prior):
                prior.append(self._world_summary(candidate['seed'], candidate['plan']['opening']))
                atomic_json(self.creation_history_path, prior[-50:])
            return self._activate(engine, key)

    def save(self, name):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise RuleError('請替存檔取一個簡短名稱。')
        with self.lock:
            key = uuid.uuid4().hex
            path = self.root / 'saves' / (key + '.sqlite3')
            self.engine.verify()
            self._backup(self.engine.path, path)
            saved = Engine(path)
            saved.verify()
            self.index['saves'][key] = {**self._metadata(saved, str(path)), 'name': name.strip(), 'updated_at': now()}
            self._persist()
            return {'id': key, 'name': name.strip()}

    @staticmethod
    def _backup(source, destination):
        with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                with dst:
                    src.backup(dst)

    def load(self, kind, key):
        with self.lock:
            if kind == 'campaign':
                engine = self._campaign(key)
                return self._activate(engine, key)
            if kind != 'save' or key not in self.index['saves']:
                raise RuleError('找不到這份存檔。')
            source = self._allowed(self.index['saves'][key]['path'])
            Engine(source).verify()
            branch = uuid.uuid4().hex
            path = self.root / 'campaigns' / (branch + '.sqlite3')
            self._backup(source, path)
            engine = Engine(path)
            campaign_key = self._index_campaign(engine)
            return self._activate(engine, campaign_key)
