"""Deterministic prerequisites and transactional, reviewable Freeform rulings.

Model text has no write access. Uncertain rulings need explicit approval against
the same state revision that was used to prepare the proposal.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .social import SOCIAL_EVENTS, apply_social
from .canon import (validate_canon_proposal, validate_audit, check_power,
                    apply_power, establish)
from .player_view import encounters, knowledge, map_view, validate_note, apply_note
from .physical import validate_harm, apply_harm, consistency, scene_text,ordinary_rationale


class RuleError(ValueError):
    pass


class RulingConflict(RuleError):
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


def normalize_action(raw):
    if not isinstance(raw, dict):
        raise RuleError("行動必須是物件")
    kind = raw.get("kind")
    if kind not in {"observe", "speak", "interact", "wait", "cast", "use_item", "travel", "freeform"}:
        raise RuleError("請選擇行動種類")
    action = {"kind": kind, "text": require_text(raw.get("text"), "玩家宣告")}
    for field in ("target", "ability", "item", "destination"):
        action[field] = raw.get(field, "")
        if not isinstance(action[field], str) or len(action[field]) > 120:
            raise RuleError(f"無效的 {field}")
    if 'understanding' in raw:
        from .understanding import validate_understanding
        parsed=validate_understanding(action['text'],raw['understanding'])
        if parsed['mode']=='speech' and kind!='speak':raise RuleError('發言不能被改成實際動作。')
        if parsed['mode']=='thought' and kind!='freeform':raise RuleError('內心想法不能被改成實際動作。')
        action['understanding']=copy.deepcopy(parsed)
    if 'compound' in raw:
        if type(raw['compound']) is not bool or 'understanding' not in action:
            raise RuleError('複合宣告需要有效的原文理解紀錄。')
        action['compound'] = raw['compound']
    if kind == "cast" and not action["ability"]:
        raise RuleError("施法需要指定法術 ID；不能只憑敘事新增法術")
    if kind == "use_item" and not action["item"]:
        raise RuleError("使用物品需要指定物品 ID")
    if kind == "travel" and not action["destination"]:
        raise RuleError("移動需要指定目的地")
    return action


def check_action(state, action):
    """Returns a factual ruling; no LLM, dice or state mutation occurs here."""
    pc = state["pc"]
    if not pc["alive"]:
        return "blocked", f"{pc['name']}已死亡；不能繼續行動，真正的錯誤可依約定回溯修正。"
    if action.get('understanding',{}).get('mode')=='thought':
        return 'routine','你在心中思考，沒有把這個念頭說出口，也沒有採取其中的行動。'
    from .references import targeted_observation
    if targeted_observation(state, action) is not None:
        return 'routine','觀察已知人物，只呈現目前位置已可確認的描述，不新增外觀、內心或互動。'
    if action.get('understanding') and action['kind']=='speak' and not action['target']:
        present=[npc for npc in state['npcs'].values() if npc['known'] and npc['location']==pc['location']]
        if len(present)>1:return 'review','這句話在當前場景說出；由在場人物自然反應或回問對象，不由系統要求補填名字。'
    target = action["target"]
    if target:
        npc = state["npcs"].get(target)
        if not npc or not npc["known"] or npc["location"] != pc["location"]:
            return "blocked", "目標不在目前已知、可接觸的場景中；不能憑一句宣告把目標帶到面前。"
        if not npc["alive"]:
            return "blocked", "目標已死亡；這項人物互動無法進行。"
    if action["kind"] == "cast":
        ability = action["ability"]
        if ability not in pc["spells"]:
            name = state["abilities"].get(ability, {}).get("name", {"fire_magic": "火焰魔法", "unestablished_power": "未登記的超自然能力"}.get(ability, ability))
            return "blocked", f"{pc['name']}尚未學會「{name}」，因此沒有產生魔法效果，也沒有造成該魔法的傷害。"
        if 'canon' in state:
            try:
                check_power(state, {'type': 'power_use', 'actor': pc['id'],
                                   'power': ability, 'target': target or pc['id']}, RuleError)
            except RuleError as exc:
                return 'blocked', str(exc)
        rule = state["abilities"].get(ability)
        if not rule or not rule.get("source") or not rule.get("effect"):
            return "clarify", "法術已記錄，但缺少已接受的效果或規則來源，先補足規則再裁定。"
        for resource, cost in rule.get("cost", {}).items():
            if resource not in pc["resources"]:
                return "clarify", f"缺少 {resource} 的確定值，不能猜測資源。"
            if pc["resources"][resource] < cost:
                return "blocked", f"{resource} 不足，不能施放此法術。"
        for item in rule.get("requires", []):
            if pc["inventory"].get(item, 0) < 1:
                return "blocked", f"缺少施法必需品：{item}。"
        return "review", "施法前提成立；是否命中、對方反應及後果仍需依場景裁定，不能自動成功。"
    if action["kind"] == "use_item" and pc["inventory"].get(action["item"], 0) < 1:
        return "blocked", "目前物品紀錄沒有這件可用物品。未建立的裝備不視為已持有。"
    if action["kind"] == "travel":
        route = state["locations"][pc["location"]]["exits"].get(action["destination"])
        if not route or not route.get("known"):
            return "clarify", "沒有已知的通路；需要先建立路線，不能直接跳到未知地點。"
        if route.get("clear") is True:
            if action.get('compound') or action.get('understanding',{}).get('mode') == 'mixed':
                return 'review', '路線成立；仍須依原文順序裁定完整連續行動及人物反應，不能只完成移動。'
            return "routine", "沿已知且無已知阻礙的短路線移動。"
        return "review", "路線有未解條件，需裁定後才能移動。"
    if action["kind"] == "observe":
        if action.get('compound') or action.get('understanding',{}).get('mode') == 'mixed':
            return 'review', '保留觀察與發言的完整宣告，不能只完成觀察而略去其他部分。'
        return "routine", "提供已知、當下可見的環境；不另作搜索或發現隱藏事實。"
    return "review", "玩家宣告是嘗試。需要具體裁定；尚未改變角色能力、NPC 或世界狀態。"


def validate_proposal(state, action, proposal):
    if not isinstance(proposal, dict) or set(proposal) != {"outcome", "reason", "narration", "events"}:
        raise RuleError("裁定需要 outcome、reason、narration、events 四個欄位")
    if proposal["outcome"] not in {"success", "failure", "partial", "clarify"}:
        raise RuleError("無效的裁定結果")
    require_text(proposal["reason"], "裁定依據")
    require_text(proposal["narration"], "敘事", 8000)
    events = proposal["events"]
    if action.get('understanding',{}).get('mode')=='thought' and events:
        raise RuleError('未說出口的想法不能令 NPC 回應或改變世界。')
    if not isinstance(events, list) or len(events) > 20:
        raise RuleError("無效的事件清單")
    if proposal["outcome"] == "clarify" and events:
        raise RuleError("待釐清的行動不能修改世界")
    if any(not isinstance(event, dict) for event in events):
        raise RuleError('事件必須是物件')
    # Model output is untrusted. Check the shape before any semantic validator
    # indexes a field; malformed events must never escape as KeyError('type').
    shapes={
        'harm':{'type','actor','target','weapon','condition','fatal','basis'},
        'npc_update':{'type','npc','field','value'},
        'power_use':{'type','actor','power','target'},
        'fact':{'type','text','visibility'},'move':{'type','destination'},
        'npc_move':{'type','npc','from','destination','basis'},
        'open_matter':{'type','text'},'establish_npc':{'type','npc'},
    }
    allowed=set(shapes)|SOCIAL_EVENTS|{'character_note'}
    for event in events:
        kind=event.get('type')
        if not isinstance(kind,str) or kind not in allowed:
            raise RulingConflict('模型回應的事件類型缺漏或無效，這份草案未生效。請依指定格式補上有效的 type；沒有狀態變化就用 events:[]，不要猜測或套用事件。')
        if kind in shapes and set(event)!=shapes[kind]:
            raise RulingConflict('模型回應的 '+kind+' 事件欄位不完整，這份草案未生效。請依指定格式提供必要欄位；沒有變化就用 events:[]。')
        if kind in shapes:
            for field in shapes[kind]-{'type','fatal'}:
                if kind=='establish_npc' and field=='npc':continue
                if not isinstance(event[field],str):
                    raise RulingConflict('模型回應的事件欄位格式不正確，這份草案未生效。請用指定文字欄位描述事件，不要混入陣列或其他格式。')
            if kind=='harm' and type(event['fatal']) is not bool:
                raise RulingConflict('傷勢的死亡標記需要 true 或 false，這份草案未生效。')
    validate_canon_proposal(state, action, proposal, RuleError)
    consistency(state,action,proposal,RulingConflict)
    ordinary_rationale(state,action,proposal,RulingConflict)
    original_state=state
    # Validate in order on a private shadow, so establishment precedes response.
    state = copy.deepcopy(state)
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise RuleError("事件必須是物件")
        kind = event.get("type")
        if kind == 'power_use' and 'canon' in state:
            check_power(state, event, RuleError)
        elif kind=='harm':
            validate_harm(original_state,action,proposal,event,RuleError)
            apply_harm(state,event,state['revision']+1)
        elif kind == 'character_note':
            validate_note(state, event, proposal['narration'], RuleError)
        elif kind in SOCIAL_EVENTS:
            apply_social(state, action, event, state["revision"] + 1, index, RuleError)
        elif kind == "npc_update":
            if set(event) != {"type", "npc", "field", "value"}:
                raise RuleError("NPC 更新欄位不正確")
            npc = state["npcs"].get(event["npc"])
            if not npc or npc["location"] != state["pc"]["location"]:
                raise RuleError("不能更新不在場人物")
            if event["field"] not in {"condition", "priorities", "appraisal", "attraction", "stance"}:
                raise RuleError("只能更新 NPC 當前互動狀態，不能直接改寫身分或生死")
            require_text(event["value"], "NPC 狀態", 1000)
        elif kind == "fact":
            if set(event) != {"type", "text", "visibility"} or event["visibility"] not in {"public", "private"}:
                raise RuleError("事實必須標明 public 或 private")
            require_text(event["text"], "事實", 1500)
        elif kind == "move":
            if set(event) != {"type", "destination"} or action["kind"] != "travel" or event["destination"] != action["destination"]:
                raise RuleError("不得替玩家選擇未宣告的移動")
            if proposal["outcome"] not in {"success", "partial"}:
                raise RuleError("失敗不能同時完成移動")
            route = state['locations'][state['pc']['location']]['exits'].get(event['destination'])
            if not route or not route.get('known'):
                raise RuleError('移動事件沒有已知通路，或重複執行同一段移動。')
            # Later reactions are checked at the arrival location, but only
            # after this authorized move event. The real state is still intact.
            state['pc']['location'] = event['destination']
        elif kind == "npc_move":
            if set(event) != {"type", "npc", "from", "destination", "basis"}:
                raise RuleError("人物移動需要 npc、from、destination、basis")
            npc = state["npcs"].get(event["npc"])
            if not npc or not npc["alive"] or npc["location"] != state["pc"]["location"] or event["from"] != npc["location"]:
                raise RuleError("NPC 移動的當前位置不符，或人物不在場")
            if event["destination"] not in state["locations"] or event["destination"] not in state["locations"][npc["location"]]["exits"]:
                raise RuleError("NPC 不能瞬移到沒有已建立通路的地方")
            require_text(event["basis"], "人物選擇離開的具體原因", 1800)
            state["npcs"][event["npc"]]["location"] = event["destination"]
        elif kind == "establish_npc":
            if set(event) != {"type", "npc"}:
                raise RuleError("新人物欄位不正確")
            npc = event["npc"]
            required = {"id", "name", "location", "known", "alive", "description", "anchor", "encounter", "knowledge", "conditions"}
            if not isinstance(npc, dict) or set(npc) != required or npc["id"] in state["npcs"]:
                raise RuleError("新人物需要完整資料且不能覆蓋既有人物")
            for field in ("id", "name", "description"):
                require_text(npc[field], field, 1500)
            if npc["location"] not in state["locations"] or type(npc["known"]) is not bool or type(npc["alive"]) is not bool:
                raise RuleError("新人物位置或存活狀態無效")
            for field, keys in (("anchor", {"values", "concern", "boundary", "levers"}),
                                ("encounter", {"condition", "priorities", "appraisal", "attraction", "stance"})):
                if not isinstance(npc[field], dict) or set(npc[field]) != keys:
                    raise RuleError("新人物缺少個人動機或五項互動基礎")
                for value in npc[field].values():
                    require_text(value, field, 1500)
            for field in ("knowledge", "conditions"):
                if not isinstance(npc[field], list) or any(not isinstance(v, str) for v in npc[field]):
                    raise RuleError("人物知識及狀況需要文字清單")
            state["npcs"][npc["id"]] = copy.deepcopy(npc)
        elif kind == "open_matter":
            if set(event) != {"type", "text"}:
                raise RuleError("未決事項欄位不正確")
            require_text(event["text"], "未決事項", 1500)
        else:
            raise RuleError("模型不能新增能力、物品、資源、生死或任意修改狀態；這需要另外的明確規則與管理操作")
    if sum(e["type"] == "move" for e in events) > 1:
        raise RuleError("同一行動不可重複移動")
    new_ids = [e["npc"]["id"] for e in events if e["type"] == "establish_npc"]
    if len(set(new_ids)) != len(new_ids):
        raise RuleError("同一提案含重複人物 ID")
    return copy.deepcopy(proposal)


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
                CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    action TEXT NOT NULL, proposal TEXT NOT NULL, source TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS turn_updates (source_revision INTEGER PRIMARY KEY,
                    body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',error TEXT);
            """)
            columns = {r[1] for r in db.execute('PRAGMA table_info(proposals)')}
            if 'audit' not in columns:
                db.execute('ALTER TABLE proposals ADD COLUMN audit TEXT')
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
        original=require_text(text,'你的行動或台詞')
        narration=require_text(reply.get('narration'),'主持人回覆',20000)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT body,after_state FROM journal WHERE request_id=?',(request_id,)).fetchone()
            if prior:
                body=json.loads(prior['body'])
                if body['action']['text']!=original:raise RuleError('同一行動識別不能改成另一句宣告。')
                return {'status':body['status'],'narration':body['narration'],'revision':json.loads(prior['after_state'])['revision']}
            state=json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
            if state['revision']!=revision:raise RuleError('故事在生成期間已更新，請重新載入目前進度。')
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
                'ability_source_check':reply.get('ability_source_check',[]),
                'ability_source_correction':reply.get('ability_source_correction',False)})

    def public_state(self, state=None, history=None):
        state = self.state() if state is None else copy.deepcopy(state)
        from .names import aliases, display
        name_registry=aliases(state)
        history = self.history(include_encounters=True) if history is None else history
        people, visited = knowledge(state, history)
        atlas = map_view(state, history)
        state['people'] = people
        state['atlas'] = atlas
        state['locations'][state['pc']['location']]['description']=scene_text(state)
        state['npcs'] = {key: npc for key,npc in state['npcs'].items()
                         if npc['location']==state['pc']['location'] and npc['known']}
        known_places={node['id'] for node in atlas['nodes']}
        state['locations']={key: place for key,place in state['locations'].items() if key in known_places}
        for key,place in state['locations'].items():
            place['exits']={target: route for target,route in place['exits'].items() if route['known'] and target in known_places}
            if key!=state['pc']['location']:
                place['description']='你曾抵達的地方，最新情況需要回去確認。' if key in visited else '已知通路上的地方，抵達後再了解。'
        state.pop('people_notes',None)
        state.pop('story',None)  # Future chapters and fixed secrets are GM-only.
        state['pc'].pop('injuries',None)
        for npc in state["npcs"].values():
            npc.pop("anchor", None)
            npc.pop("encounter", None)
            npc.pop("knowledge", None)
            npc.pop("inner_life", None)
            npc.pop('injuries',None)
            npc.pop('dialogue',None)  # Internal conversation provenance, not a player panel.
            npc.pop('player_view',None)  # Projected into the player's people cards.
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
        return display(state,name_registry)

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

    def submit(self, raw, request_id, expected_revision):
        action = normalize_action(raw)
        request_id = require_text(request_id, "request_id", 120)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT body, after_state FROM journal WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                body = json.loads(existing["body"])
                if body.get("action") != action:
                    raise RuleError("同一請求 ID 不能代表不同的行動")
                return {"status": body["status"], "narration": body["narration"],
                        "revision": json.loads(existing["after_state"])["revision"]}
            state = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
            if expected_revision != state["revision"]:
                raise RuleError("世界已更新，請重新載入再裁定")
            status, reason = check_action(state, action)
            if status == "review":
                return {"status": "review", "reason": reason, "action": action, "revision": state["revision"]}
            after = copy.deepcopy(state)
            narration = reason
            if status == "routine" and action.get('understanding',{}).get('mode')!='thought':
                if action["kind"] == "travel":
                    after["pc"]["location"] = action["destination"]
                place = after["locations"][after["pc"]["location"]]
                narration = scene_text(after)
                present = [n["description"] for n in after["npcs"].values()
                           if n["location"] == after["pc"]["location"] and n["known"] and not n.get('injuries')]
                narration += ("\n" + "\n".join(present)) if present else ""
                from .references import targeted_observation
                observed = targeted_observation(after, action)
                if observed is not None: narration = observed
            return self._append(db, state, after, request_id,
                {"status": status, "action": action, "reason": reason, "narration": narration, "events": []})

    def propose(self, raw_action, proposal, revision, source="human", audit=None):
        action = normalize_action(raw_action)
        state = self.state()
        if revision != state["revision"]:
            raise RuleError("提案使用過時的狀態")
        if check_action(state, action)[0] != "review":
            raise RuleError("這項行動已有明確前提裁定，不能以模型提案繞過")
        proposal = validate_proposal(state, action, proposal)
        validate_audit(state, proposal, audit, RuleError, action)
        pid = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO proposals(id,revision,action,proposal,source,audit) VALUES (?,?,?,?,?,?)",
                       (pid, revision, canonical(action), canonical(proposal), source, canonical(audit)))
        return {"id": pid, "revision": revision, "action": action, "proposal": proposal, "source": source,
                'grounding_checked': 'canon' in state}

    def approve(self, proposal_id, request_id, defer_people=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT body,after_state FROM journal WHERE request_id=?", (request_id,)).fetchone()
            if prior:
                body = json.loads(prior["body"])
                if body.get("proposal_id") != proposal_id:
                    raise RuleError("同一請求 ID 不可批准不同提案")
                return {"status": body["status"], "narration": body["narration"],
                        "revision": json.loads(prior["after_state"])["revision"]}
            row = db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
            if not row or row["used"]:
                raise RuleError("提案不存在或已處理")
            state = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
            if row["revision"] != state["revision"]:
                raise RuleError("世界已更新；舊提案不能套用")
            action, proposal = json.loads(row["action"]), json.loads(row["proposal"])
            if check_action(state, action)[0] != "review":
                raise RuleError("前提已變更，需重新裁定")
            validate_proposal(state, action, proposal)
            audit = json.loads(row['audit']) if row['audit'] else None
            validate_audit(state, proposal, audit, RuleError, action)
            after = copy.deepcopy(state)
            if action["kind"] == "cast" and proposal["outcome"] in {"success", "partial"}:
                for resource, cost in state["abilities"][action["ability"]].get("cost", {}).items():
                    after["pc"]["resources"][resource] -= cost
            for index, event in enumerate(proposal["events"]):
                if event['type'] == 'power_use':
                    apply_power(after, event, state['revision'] + 1, RuleError)
                elif event['type']=='harm':
                    apply_harm(after,event,state['revision']+1)
                elif event['type'] == 'character_note':
                    apply_note(after, event, state['revision'] + 1)
                elif event["type"] in SOCIAL_EVENTS:
                    apply_social(after, action, event, state["revision"] + 1, index, RuleError)
                elif event["type"] == "npc_update":
                    after["npcs"][event["npc"]]["encounter"][event["field"]] = event["value"]
                elif event["type"] == "fact":
                    after["facts"].append({"text": event["text"], "visibility": event["visibility"], "source": proposal_id})
                elif event["type"] == "move":
                    after["pc"]["location"] = event["destination"]
                elif event["type"] == "npc_move":
                    after["npcs"][event["npc"]]["location"] = event["destination"]
                elif event["type"] == "establish_npc":
                    after["npcs"][event["npc"]["id"]] = copy.deepcopy(event["npc"])
                elif event["type"] == "open_matter":
                    after["open_matters"].append(event["text"])
            from .dialogue import record_exchange
            record_exchange(after,action,proposal,state['revision']+1,state['npcs'].get(action.get('target')))
            db.execute("UPDATE proposals SET used=1 WHERE id=?", (proposal_id,))
            result=self._append(db, state, after, request_id,
                {"status": "approved", "proposal_id": proposal_id, "action": action,
                 "reason": proposal["reason"], "narration": proposal["narration"], "events": proposal["events"],
                 'grounding_audit': audit})
            if defer_people and (not action.get('target') or after['npcs'].get(action['target'],{}).get('alive',False)):
                from .turn_updates import enqueue
                enqueue(db,state,action,proposal,result['revision'])
            return result

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

    def rewind(self, target_revision, expected_revision, request_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT body,after_state FROM journal WHERE request_id=?", (request_id,)).fetchone()
            if prior:
                body = json.loads(prior["body"])
                if body.get("status") != "rewound" or body.get("target_revision") != target_revision:
                    raise RuleError("同一請求 ID 不可代表不同回溯")
                return {"status": "rewound", "narration": body["narration"],
                        "revision": json.loads(prior["after_state"])["revision"]}
            state = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
            if expected_revision != state["revision"]:
                raise RuleError("世界已更新，請重新確認回溯位置")
            if type(target_revision) is not int or not 0 <= target_revision < state["revision"]:
                raise RuleError("無效的回溯版本")
            column = "before_state" if target_revision == 0 else "after_state"
            row = db.execute(f"SELECT {column} FROM journal WHERE revision=?", (1 if target_revision == 0 else target_revision,)).fetchone()
            after = json.loads(row[0])
            return self._append(db, state, after, request_id,
                {"status": "rewound", "target_revision": target_revision, "events": [],
                 "narration": f"已回溯到版本 {target_revision} 的世界狀態；原事件仍保留在歷史中。"})

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

    def grant_spell(self, ability_id, definition, expected_revision, request_id):
        """Explicit GM maintenance; never called from the model proposal path."""
        ability_id = require_text(ability_id, "能力 ID", 80)
        if not isinstance(definition, dict) or set(definition) != {"name", "effect", "source"}:
            raise RuleError("能力設定需要 name、effect、source，這是明確場外設定變更")
        for key in definition:
            require_text(definition[key], key, 2000)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
            if 'canon' in state:
                raise RuleError('此戰役請使用世界建立登記能力及觸發條件，不能略過身分紀錄')
            if expected_revision != state["revision"]:
                raise RuleError("設定已更新，請重新載入")
            if ability_id in state["abilities"]:
                raise RuleError("該能力已存在；不可重複新增或覆蓋")
            after = copy.deepcopy(state)
            after["abilities"][ability_id] = copy.deepcopy(definition)
            after["pc"]["spells"].append(ability_id)
            return self._append(db, state, after, request_id,
                {"status": "maintenance", "events": [], "ability": ability_id,
                 "narration": f"主持人明確更新設定：班學會了{definition['name']}。來源：{definition['source']}"})

    def maintain(self, changes, source, expected_revision, request_id):
        """Explicit OOC editor for exact values, world establishment and outcomes.

        This is a human authority boundary, never an accepted model event type.
        No implied HP, XP, combat rule, time tick or resource reset is installed.
        """
        source = require_text(source, "設定來源與裁定原因", 2000)
        if not isinstance(changes, dict) or not changes or set(changes) - {"resources", "inventory", "conditions", "alive", "new_location"}:
            raise RuleError("設定只能包含 resources、inventory、conditions、alive 或 new_location")
        for field in ("resources", "inventory"):
            if field in changes:
                values = changes[field]
                if not isinstance(values, dict) or any(not isinstance(k, str) or not k.strip() or type(v) is not int or v < 0 for k, v in values.items()):
                    raise RuleError("資源與物品必須是非負整數的明確值")
        if "conditions" in changes and (not isinstance(changes["conditions"], list) or any(not isinstance(v, str) for v in changes["conditions"])):
            raise RuleError("狀況需要文字清單")
        if "alive" in changes and type(changes["alive"]) is not bool:
            raise RuleError("alive 需要布林值")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
            if expected_revision != state["revision"]:
                raise RuleError("世界已更新，請重新載入")
            if changes.get("alive") is True and not state["pc"]["alive"]:
                raise RuleError("永久死亡不能用一般狀態更新復活；真正錯誤請用明確回溯修復")
            after = copy.deepcopy(state)
            for field in ("resources", "inventory", "conditions", "alive"):
                if field in changes:
                    after["pc"][field] = copy.deepcopy(changes[field])
            if "new_location" in changes:
                location = changes["new_location"]
                if not isinstance(location, dict) or set(location) != {"id", "name", "description", "from", "clear"}:
                    raise RuleError("新地點需要 id、name、description、from、clear")
                for field in ("id", "name", "description", "from"):
                    require_text(location[field], field, 2000)
                if location["id"] in state["locations"] or location["from"] not in state["locations"] or type(location["clear"]) is not bool:
                    raise RuleError("地點已存在或通路無效")
                after["locations"][location["id"]] = {"name": location["name"], "description": location["description"],
                    "exits": {location["from"]: {"known": True, "clear": location["clear"]}}}
                after["locations"][location["from"]]["exits"][location["id"]] = {"known": True, "clear": location["clear"]}
            return self._append(db, state, after, request_id,
                {"status": "maintenance", "events": [], "changes": changes, "source": source,
                 "narration": "主持人已明確更新設定。依據：" + source})

    def establish(self, data, source, expected_revision, request_id):
        source = require_text(source, '先行設定來源或已接受事件', 2000)
        request_id = require_text(request_id, 'request_id', 120)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT body,after_state FROM journal WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                body = json.loads(prior['body'])
                if body.get('establishment') != data or body.get('source') != source:
                    raise RuleError('同一請求 ID 不能建立不同設定')
                return {'status': body['status'], 'narration': body['narration'],
                        'revision': json.loads(prior['after_state'])['revision']}
            state = json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
            if state['revision'] != expected_revision:
                raise RuleError('世界已更新，請重新載入')
            after = copy.deepcopy(state)
            if isinstance(data, dict) and data.get('kind') == 'npc':
                if set(data) != {'kind', 'npc', 'identity'}:
                    raise RuleError('新人物需要 kind、npc、identity')
                ordinary = copy.deepcopy(state)
                ordinary.pop('canon', None)
                action = normalize_action({'kind': 'freeform', 'text': '主持人先行建立新人物，尚未解算其行動。'})
                validate_proposal(ordinary, action, {'outcome': 'success', 'reason': source,
                    'narration': '先行建立人物。', 'events': [{'type': 'establish_npc', 'npc': data['npc']}]})
                after['npcs'][data['npc']['id']] = copy.deepcopy(data['npc'])
                identity = data['identity']
                if not isinstance(identity, dict) or identity.get('actor') != data['npc']['id'] or identity.get('kind') != 'identity':
                    raise RuleError('新人物身分必須與新人物 ID 一致')
                establish(after, identity, source, state['revision'] + 1, RuleError)
            else:
                establish(after, data, source, state['revision'] + 1, RuleError)
            return self._append(db, state, after, request_id,
                {'status': 'maintenance', 'establishment': data, 'source': source, 'events': [],
                 'narration': '主持人已先行建立設定。依據：' + source})
