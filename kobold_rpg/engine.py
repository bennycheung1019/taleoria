"""Transactional RPG OS campaign state and verifiable event journal."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .player_view import encounters, knowledge, map_view
from .physical import scene_text


class RuleError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def initial_state():
    return {
        "campaign_id": "ben-local-" + uuid.uuid4().hex[:10],
        "revision": 0,
        "contract": {
            "engine": "freeform-v1.01-adapter", "language": "繁體中文",
            "genre": "黑暗奇幻", "difficulty": "Hard", "permadeath": True,
            "play_form": "開放沙盒", "cuts": "不越過未決的重要選擇",
            "retcon": "可要求回溯；真正錯誤可修正", "randomness": "無強制擲骰",
        },
        "pc": {"id": "ben", "name": "班（Ben）", "alive": True,
               "location": "gate", "capabilities": ["追蹤", "調查", "荒野生存"],
               "spells": [], "inventory": {}, "resources": {}, "conditions": [],
               "goal": "希望成為世界之王；成功不保證"},
        "abilities": {},
        "locations": {"gate": {"name": "邊境城門外", "description":
            "雨水沿城門的石拱流下。城門半掩，左側有一座空的避雨棚，守衛站在門燈下。",
            "exits": {"shelter": {"clear": True, "known": True}}},
            "shelter": {"name": "城門旁的避雨棚", "description":
            "木棚緊靠外城牆，城門和門燈仍在視線內。棚下沒有其他人。",
            "exits": {"gate": {"clear": True, "known": True}}}},
        "npcs": {"hark": {"id": "hark", "name": "哈克（Hark）", "location": "gate",
            "known": True, "alive": True,
            "description": "一名披著雨斗篷、腰佩短劍的成年守衛。",
            "anchor": {"values": "保住這份守門工作，照顧住在城內的弟弟",
                       "concern": "交班的人未到，不能擅離城門",
                       "boundary": "不接受陌生人碰觸自己的衣物或武器",
                       "levers": "可信的消息、實際協助、能核實的保證"},
            "encounter": {"condition": "清醒、衣物濕冷，正在守門",
                          "priorities": "等候交班並維持城門秩序",
                          "appraisal": "知道班在附近，尚不了解他的意圖",
                          "attraction": "目前沒有建立吸引；不等於敵意",
                          "stance": "可簡短交談，尚無信任或協助承諾"},
            "knowledge": ["自己守門的職責"], "conditions": []}},
        "facts": [], "open_matters": [],
    }


def require_text(value, field, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RuleError(f"{field} 需要 1–{maximum} 字的文字")
    return value.strip()


class Engine:
    def __init__(self, database, seed=None):
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS journal (revision INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    body TEXT NOT NULL, before_state TEXT NOT NULL, after_state TEXT NOT NULL,
                    previous_hash TEXT NOT NULL, hash TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO state VALUES (1, ?)", (canonical(seed if seed is not None else initial_state()),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def state(self):
        with self.connect() as db:
            return json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])

    def record_gm_reply(self,text,reply,request_id,revision):
        """Persist the RPG OS GM's reply without a second gameplay referee."""
        from .gm import record_changes
        from .story_text import story_text
        original=require_text(text,'你的行動或台詞')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT body,after_state FROM journal WHERE request_id=?',(request_id,)).fetchone()
            if prior:
                body=json.loads(prior['body'])
                if body['action']['text']!=original:raise RuleError('同一行動識別不能改成另一句宣告。')
                return {'status':body['status'],'narration':story_text(body['narration']),'revision':json.loads(prior['after_state'])['revision']}
            state=json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
            if state['revision']!=revision:raise RuleError('故事在生成期間已更新，請重新載入目前進度。')
            from .npc_visibility import reconcile_reply
            reply=reconcile_reply(state,reply)
            narration=require_text(story_text(reply.get('narration')),'主持人回覆',20000)
            try:after,bookkeeping=record_changes(state,reply.get('changes',{}),revision+1,narration)
            except Exception:
                # Bookkeeping is not a delivery/fiction approval stage.
                after,bookkeeping=copy.deepcopy(state),'incomplete'
            if reply.get('bookkeeping') in ('incomplete','plain_reply') and bookkeeping=='ready':
                bookkeeping='incomplete'
            return self._append(db,state,after,request_id,{'status':'approved',
                'source':'rpg_os_gm','action':{'kind':'freeform','text':original,'target':'','ability':'','item':'','destination':''},
                'reason':'RPG OS v1.01 主持裁定；程式保存紀錄。','narration':narration,'events':[],
                'bookkeeping':bookkeeping,'gm_changes':reply.get('changes',{}),
                'gm_references':[key for key,when in after.get('scene_memory',{}).get('contacts',{}).items() if when==revision+1],
                'ability_source_check':reply.get('ability_source_check',[]),
                'ability_source_correction':reply.get('ability_source_correction',False)})

    def public_state(self, state=None, history=None):
        state = self.state() if state is None else copy.deepcopy(state)
        from .names import aliases, display
        from .npc_visibility import mask_hidden, name_known
        private_state=copy.deepcopy(state)
        history = self.history(include_encounters=True) if history is None else history
        people, visited = knowledge(state, history)
        atlas = map_view(state, history)
        state['people'] = people
        state['atlas'] = atlas
        state['locations'][state['pc']['location']]['description']=scene_text(state)
        state['npcs'] = {key: npc for key,npc in state['npcs'].items()
                         if npc['location']==state['pc']['location'] and npc['known'] and name_known(npc)}
        known_places={node['id'] for node in atlas['nodes']}
        state['locations']={key: place for key,place in state['locations'].items() if key in known_places}
        for key,place in state['locations'].items():
            place['exits']={target: route for target,route in place['exits'].items() if route['known'] and target in known_places}
            if key!=state['pc']['location']:
                place['description']='你曾抵達的地方，最新情況需要回去確認。' if key in visited else '已知通路上的地方，抵達後再了解。'
        state.pop('people_notes',None)
        state.pop('story',None)  # Future chapters and fixed secrets are GM-only.
        state.pop('scene_memory',None)  # Retrieval indices are host bookkeeping.
        state['pc'].pop('injuries',None)
        for npc in state["npcs"].values():
            npc.pop("anchor", None)
            npc.pop("encounter", None)
            npc.pop("knowledge", None)
            npc.pop("inner_life", None)
            npc.pop('injuries',None)
            npc.pop('dialogue',None)  # Internal conversation provenance, not a player panel.
            npc.pop('player_view',None)  # Legacy save annotations are not displayed.
        state["facts"] = [f for f in state["facts"] if f["visibility"] == "public"]
        if 'canon' in state:
            own_identity = state['canon']['actors'].get(state['pc']['id'], {})
            state['pc']['known_powers']=[{'id':key,'name':state['canon']['powers'][key]['name'],
                                        'effect':state['canon']['powers'][key]['effect']}
                                       for key in own_identity.get('powers',[]) if key in state['canon']['powers']]
            for field in ('species', 'role'):
                if field in own_identity:
                    state['pc'].setdefault(field, own_identity[field])
            state['canon_status'] = {'enabled': True, 'actors': len(state['canon']['actors']),
                                     'powers': len(state['canon']['powers']),
                                     'policy': state['contract']['canon_policy']}
            state.pop('canon')  # Private nature/powers are GM authority, not automatic PC knowledge.
        state=mask_hidden(state,private_state)
        return display(state,aliases(state))

    def _append(self, db, state, after, request_id, body):
        after["revision"] = state["revision"] + 1
        previous = db.execute("SELECT hash FROM journal ORDER BY revision DESC LIMIT 1").fetchone()
        prev_hash = previous[0] if previous else "0" * 64
        body = {**body, "at": datetime.now(timezone.utc).isoformat()}
        before_json, after_json, body_json = map(canonical, (state, after, body))
        digest = hashlib.sha256((prev_hash + body_json + before_json + after_json).encode()).hexdigest()
        db.execute("INSERT INTO journal VALUES (?,?,?,?,?,?,?)", (after["revision"], request_id,
                   body_json, before_json, after_json, prev_hash, digest))
        db.execute("UPDATE state SET body=? WHERE id=1", (after_json,))
        return {"status": body["status"], "narration": body["narration"], "revision": after["revision"]}

    def history(self, include_encounters=False):
        with self.connect() as db:
            result=[]
            for r in db.execute('SELECT revision,body,before_state,after_state FROM journal ORDER BY revision'):
                row={'revision':r['revision'],**json.loads(r['body'])}
                if include_encounters:
                    before=json.loads(r['before_state']);after=json.loads(r['after_state'])
                    row['_encounters']=encounters(before)+encounters(after)
                    row['_visited']=[before['pc']['location'],after['pc']['location']]
                    row['_origin']=before['pc']['location']
                result.append(row)
            return result

    def verify(self):
        prev = "0" * 64
        last_after = None
        revision = 0
        with self.connect() as db:
            for row in db.execute("SELECT * FROM journal ORDER BY revision"):
                digest = hashlib.sha256((prev + row["body"] + row["before_state"] + row["after_state"]).encode()).hexdigest()
                if row["previous_hash"] != prev or row["hash"] != digest or row["revision"] != revision + 1:
                    raise RuleError("事件紀錄驗證失敗")
                if last_after is not None and row["before_state"] != last_after:
                    raise RuleError("事件之間的世界狀態不連續")
                prev = digest
                last_after = row["after_state"]
                revision = row["revision"]
            current = db.execute("SELECT body FROM state WHERE id=1").fetchone()[0]
            if last_after is not None and current != last_after:
                raise RuleError("目前狀態與最後一筆事件不一致")
        return True
