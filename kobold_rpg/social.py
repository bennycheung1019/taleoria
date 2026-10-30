"""Qualitative, directed social state for the RPG OS Freeform adapter.

These records support judgment; they do not compute willingness, love, consent,
or a personality score. Semantic causality still requires GM review.
"""
import copy
import re


FACETS = {"trust", "affection", "respect", "resentment", "fear",
          "aesthetic_attraction", "sexual_attraction", "romantic_interest",
          "commitment", "boundaries"}
LIMIT_FACETS = {"sexual_attraction", "romantic_interest"}
SOCIAL_EVENTS = {"npc_personality", "personality_change", "social_experience"}


def inner_life(npc):
    # A missing legacy field is an unresolved gap, never a neutral relationship.
    return copy.deepcopy(npc.get("inner_life", {
        "personality": None, "limits": [], "current_emotions": [],
        "relationships": {}, "memories": [], "personality_history": []}))


def _text(value, name, error, maximum=1800):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise error(f"{name} 需要具體文字，不可用分數代替")
    if re.fullmatch(r"\s*[+-]?\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?\s*%?\s*", value):
        raise error(f"{name} 不使用通用心理分數或百分比，請描述具體感受與關係")


def _subject(state, entity_id, error):
    if entity_id == state["pc"]["id"]:
        return state["pc"]
    if not isinstance(entity_id, str) or entity_id not in state["npcs"]:
        raise error("關係對象必須是已存在的人物")
    return state["npcs"][entity_id]


def _limits(state, owner, limits, error):
    if not isinstance(limits, list) or len(limits) > 12:
        raise error("吸引適用性限制需要明確清單")
    seen = set()
    for limit in limits:
        if not isinstance(limit, dict) or set(limit) != {"subject", "facet", "reason"}:
            raise error("適用性限制需要 subject、facet、reason")
        _subject(state, limit["subject"], error)
        if limit["subject"] == owner or limit["facet"] not in LIMIT_FACETS:
            raise error("限制只適用於明確不相容的性／浪漫吸引，不把工作或婚約當成沒有感情能力")
        _text(limit["reason"], "限制的既定依據", error)
        key = (limit["subject"], limit["facet"])
        if key in seen:
            raise error("重複的適用性限制")
        seen.add(key)


def _memories(life, ids, error):
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids):
        raise error("人格改變需要已接受的經歷作為依據")
    known = {m["id"] for m in life["memories"]}
    if any(i not in known for i in ids):
        raise error("不能引用未發生或別人的私密記憶來改變人格")


def apply_social(state, action, event, revision, index, error=ValueError):
    """Validate and apply to a caller-owned shadow/transaction snapshot."""
    kind = event.get("type")
    npc_id = event.get("npc")
    if not isinstance(npc_id, str) or npc_id not in state["npcs"]:
        raise error("情緒或人格的擁有人必須是既有人物")
    npc = state["npcs"][npc_id]
    life = inner_life(npc)
    if not npc["alive"]:
        raise error("不能替已死亡的人物建立新的當下情緒")
    if npc["location"] != state["pc"]["location"]:
        raise error("此版只處理在場人物的實際經歷；不能讓遠方 NPC 自動知道玩家行動")

    if kind == "npc_personality":
        if set(event) != {"type", "npc", "description", "basis", "limits"}:
            raise error("人格建立需要 description、basis、limits")
        if life["personality"] is not None:
            raise error("人格已建立，不可每次交談重寫；需有經歷依據的 personality_change")
        if any(m["revision"] == revision for m in life["memories"]):
            raise error("新性格需在本回合依賴它的反應之前建立，不能事後補造原因")
        _text(event["description"], "個人性格", error)
        _text(event["basis"], "新建立人格的依據與適用範圍", error)
        _limits(state, npc_id, event["limits"], error)
        life["personality"] = {"description": event["description"], "basis": event["basis"],
                               "established_revision": revision}
        life["limits"] = copy.deepcopy(event["limits"])
    elif kind == "personality_change":
        if set(event) != {"type", "npc", "before", "after", "basis", "memory_ids"}:
            raise error("人格改變需要 before、after、basis、memory_ids")
        if life["personality"] is None or life["personality"]["description"] != event["before"]:
            raise error("人格的既有版本不符；不可倒改未建立的人格")
        _text(event["after"], "改變後人格", error)
        _text(event["basis"], "人格改變的具體因果", error)
        _memories(life, event["memory_ids"], error)
        # A current reaction must not manufacture its own earlier disposition.
        if any(m["revision"] >= revision for m in life["memories"] if m["id"] in event["memory_ids"]):
            raise error("人格改變需引用先前已接受的經歷，不能用同一個新回覆製造其過去原因")
        life["personality_history"].append(copy.deepcopy(life["personality"]))
        life["personality"] = {"description": event["after"], "basis": event["basis"],
                               "established_revision": revision, "memory_ids": event["memory_ids"]}
        # Applicability limits are not removed by personality drift or pursuit.
    elif kind == "social_experience":
        required = {"type", "npc", "subject", "observed", "interpretation", "emotions", "changes", "recalls"}
        if set(event) != required:
            raise error("社交經歷需要 subject、observed、interpretation、emotions、changes、recalls")
        subject = _subject(state, event["subject"], error)
        if event["subject"] == npc_id or subject["location"] != npc["location"]:
            raise error("直接經歷的對象須在場且不是自己；此版不推定遠距傳訊")
        _text(event["observed"], "NPC 實際感知到的事件", error)
        _text(event["interpretation"], "NPC 依自身性格形成的解讀", error)
        emotions, changes, recalls = event["emotions"], event["changes"], event["recalls"]
        if not isinstance(emotions, list) or not emotions or len(emotions) > 6:
            raise error("情緒需要簡短文字清單；可同時有感激、擔心等矛盾感受")
        for emotion in emotions:
            _text(emotion, "情緒", error, 500)
        if not isinstance(changes, dict) or set(changes) - FACETS:
            raise error("關係面向無效；信任、感情、吸引與承諾需分開")
        if not isinstance(recalls, list) or len(recalls) > 8 or any(not isinstance(i, str) for i in recalls):
            raise error("recalls 必須列出此人物自己的既有記憶 ID")
        if recalls:
            _memories(life, recalls, error)
        relation = copy.deepcopy(life["relationships"].get(event["subject"], {"facets": {}, "history": []}))
        for facet, change in changes.items():
            if not isinstance(change, dict) or set(change) != {"before", "after"}:
                raise error("關係改變需要 before 與 after；未建立面向的 before 為 null")
            if change["before"] != relation["facets"].get(facet):
                raise error("關係改變與目前紀錄不一致，不能重置或覆蓋已累積的感情")
            _text(change["after"], "改變後的關係", error)
            if any(l["subject"] == event["subject"] and l["facet"] == facet for l in life["limits"]):
                raise error("此吸引面向已有明確不相容限制；追求、感激或禮物不能自動移除")
        memory_id = f"social-{revision}-{index}"
        memory = {"id": memory_id, "revision": revision, "subject": event["subject"],
                  "observed": event["observed"], "interpretation": event["interpretation"],
                  "emotions": copy.deepcopy(emotions), "changes": copy.deepcopy(changes),
                  "recalls": copy.deepcopy(recalls), "action": copy.deepcopy(action)}
        life["memories"].append(memory)
        life["current_emotions"] = [{"feeling": e, "cause": memory_id} for e in emotions]
        for facet, change in changes.items():
            relation["facets"][facet] = change["after"]
        if changes:
            relation["history"].append({"memory": memory_id, "revision": revision, "changes": copy.deepcopy(changes)})
            life["relationships"][event["subject"]] = relation
        if event["subject"] == state["pc"]["id"] and set(changes) & {
                "aesthetic_attraction", "sexual_attraction", "romantic_interest"}:
            life.setdefault("attraction_baseline", {"text": npc["encounter"]["attraction"],
                                                     "before_revision": revision})
            npc["encounter"]["attraction"] = (
                "已變動的吸引面向以 inner_life.relationships 的對應 facets 為當前權威；"
                "未改動面向保留 attraction_baseline 的適用初始值。")
    else:
        raise error("未知的情緒事件")
    npc["inner_life"] = life


def model_context(state, action, memory_limit=6, include_target=False):
    """Bounded retrieval; canonical relationship facts always survive trimming."""
    result = copy.deepcopy(state)
    here = state["pc"]["location"]
    destination = action.get('destination') if action['kind'] == 'travel' and action.get('compound') else None
    if not state['locations'][here]['exits'].get(destination, {}).get('known'):
        destination = None
    result["npcs"] = {k: v for k, v in result["npcs"].items()
                      if v["location"] == here or (destination and v['known'] and v['location'] == destination)
                      or (include_target and k == action.get("target"))}
    arriving = {key for key, npc in result['npcs'].items() if destination and npc['location'] == destination}
    if destination:
        result['planned_arrival'] = {'destination': destination, 'characters': sorted(arriving),
            'constraint': '這些人物只能在本次宣告的移動成功、move 事件先成立後回應；出發前不在場。複合宣告的其他動作及發言仍須逐項保留，不可只完成移動。'}
    query = action["text"].lower()
    terms = set(re.findall(r"[a-z]+|[\u4e00-\u9fff]", query))
    for npc in result["npcs"].values():
        life = inner_life(npc)
        memories = life["memories"]
        referenced = {e["cause"] for e in life["current_emotions"]}
        # Relationship change evidence is retrievable even if its turn is old.
        for relation in life["relationships"].values():
            last_by_facet = {}
            for entry in relation["history"]:
                for facet in entry["changes"]:
                    last_by_facet[facet] = entry["memory"]
            referenced.update(last_by_facet.values())
        def score(memory):
            body = (memory["observed"] + " " + memory["interpretation"]).lower()
            return (memory["id"] in referenced, sum(t in body for t in terms), memory["revision"])
        selected = sorted(memories, key=score, reverse=True)[:memory_limit]
        life["memories"] = sorted(selected, key=lambda m: (m["revision"], m["id"]))
        for memory in life["memories"]:
            memory.pop("action", None)  # Retained in canonical history, not duplicated in prompt.
        # Keep current canonical facets, with a compact source pointer per facet.
        for relation in life["relationships"].values():
            relation["history"] = relation["history"][-memory_limit:]
        life["memory_scope"] = {"retrieved": len(selected), "total": len(memories),
                                 "note": "未取回的記憶仍保存；缺少必要原因時請要求釐清，不補造歷史"}
        life["personality_history"] = life["personality_history"][-2:]
        npc["inner_life"] = life
    target = result["npcs"].get(action.get("target"))
    if target:
        life = target["inner_life"]
        result["social_focus"] = {
            "npc": target["id"], "personality": life["personality"],
            "current_emotions": life["current_emotions"],
            "toward_player": life["relationships"].get(state["pc"]["id"]),
            "reminder": "人格、當下感受、既有關係與實際責任共同影響選擇；職責不是固定答案。缺少關係面向不等於零分。"}
        result["other_present"] = [{"id": k, "name": v["name"], "description": v["description"]}
                                   for k, v in result["npcs"].items() if k != target["id"]]
        result["npcs"] = {target["id"]: target}
        result["retrieval_scope"] = "只對所選目標作個人裁定。其他在場者僅有可見概況；若需其獨立反應，先取得其個人資料。"
    if 'canon' in state:
        from .canon import scoped_canon
        result['canon'] = scoped_canon(state, {state['pc']['id']} | set(result['npcs']))
    from .references import referenced_characters
    result['referenced_characters'] = referenced_characters(state, action)
    for key in arriving:
        result['referenced_characters'].pop(key, None)
    return result
