"""Prior establishment for identities and supernatural causes.

Typed permissions are deterministic. Prose grounding is an additional fallible
model check, followed by human review; it is not a proof of natural language.
"""
import copy
import hashlib
import json
import re


TRANSFORMATION = re.compile(r"變成|化為|化成|變身為|蛻變為|蜕变为|隱藏血脈|天賦覺醒|turn(?:s|ed)? into|transform(?:s|ed)? into|shapeshift", re.I)


def digest(proposal):
    return hashlib.sha256(json.dumps(proposal, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def text(value, label, error):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise error(label + "需要具體文字")


def actor(state, actor_id, error):
    if actor_id == state['pc']['id']:
        return state['pc']
    if not isinstance(actor_id, str) or actor_id not in state['npcs']:
        raise error('人物尚未建立，不能引用其身分或能力')
    return state['npcs'][actor_id]


def check_power(state, event, error):
    if set(event) != {'type', 'actor', 'power', 'target'}:
        raise error('能力使用需要 actor、power、target')
    for field in ('actor', 'power', 'target'):
        text(event[field], field, error)
    canon = state['canon']
    owner = actor(state, event['actor'], error)
    target = actor(state, event['target'], error)
    record = canon['actors'].get(event['actor'])
    rule = canon['powers'].get(event['power'])
    if not record or not rule or event['power'] not in record['powers'] or rule['actor'] != event['actor']:
        raise error('未登記的超自然能力不能使用；先建立來源、效果及條件，再於後續回合裁定')
    if rule['established_revision'] > state['revision']:
        raise error('能力必須在本次裁定前已成立，不能用結果倒造原因')
    if not owner['alive'] or not target['alive'] or owner['location'] != state['pc']['location'] or target['location'] != owner['location']:
        raise error('能力使用者及目標必須存活且在場')
    for flag in rule['requires_flags']:
        if canon['flags'].get(flag, {}).get('value') is not True:
            raise error('能力的既定觸發條件尚未成立：' + flag)
    if rule['result_form'] and event['target'] != event['actor']:
        raise error('本版已登記的形態變化只作用於能力擁有人自身')
    return rule


def validate_canon_proposal(state, action, proposal, error):
    if 'canon' not in state:
        return
    canon = state['canon']
    required = {state['pc']['id']} | {n['id'] for n in state['npcs'].values()
                                     if n['location'] == state['pc']['location']}
    if required - set(canon['actors']):
        raise error('在場人物缺少先行建立的身分紀錄；先完成世界建立')
    uses = [e for e in proposal['events'] if e.get('type') == 'power_use']
    seen = set()
    for event in uses:
        check_power(state, event, error)
        key = (event['actor'], event['power'])
        if key in seen:
            raise error('同一裁定不能重複套用同一人物的能力效果')
        seen.add(key)
        if event['actor'] == state['pc']['id'] and (action['kind'] != 'cast' or action['ability'] != event['power']):
            raise error('不能替玩家施放未宣告的能力')
        if proposal['outcome'] not in {'success', 'partial'}:
            raise error('失敗或待釐清的裁定不能同時使用能力')
    if action['kind'] == 'cast' and proposal['outcome'] in {'success', 'partial'} and not any(e['actor'] == state['pc']['id'] for e in uses):
        raise error('成功施法必須列出可驗證的 power_use 事件')
    if any(e.get('type') == 'establish_npc' for e in proposal['events']):
        raise error('新人物須先在「世界建立」登記身分與個人基礎；不能在使用其能力的同回合創造人物')
    # Conservative tripwire; ordinary metaphor/negation can require manual repair.
    body = proposal['narration'] + '\n' + json.dumps(proposal['events'], ensure_ascii=False)
    if TRANSFORMATION.search(body) and not any(check_power(state, e, error)['result_form'] for e in uses):
        raise error('草案涉及未獲授權的形態或隱藏能力變化；需要先行建立的能力與觸發依據')


def apply_power(state, event, revision, error):
    rule = check_power(state, event, error)
    if rule['result_form']:
        state['canon']['actors'][event['actor']]['current_form'] = rule['result_form']
    state['canon']['uses'].append({**copy.deepcopy(event), 'revision': revision,
                                   'effect': rule['effect'], 'source': rule['source']})


def establish(state, data, source, revision, error):
    """Only called by the explicit GM operation, never by model events."""
    if 'canon' not in state:
        raise error('此戰役尚未啟用身分與能力登記；不要自動改寫舊戰役')
    if not isinstance(data, dict):
        raise error('世界建立資料必須是物件')
    canon = state['canon']
    kind = data.get('kind')
    if kind == 'identity':
        if set(data) != {'kind', 'actor', 'species', 'role', 'forms', 'current_form'}:
            raise error('身分需要 kind、actor、species、role、forms、current_form')
        actor(state, data['actor'], error)
        if data['actor'] in canon['actors']:
            raise error('已建立的身分不能覆寫；真正錯誤可明確回溯，變身須有先行能力')
        for field in ('species', 'role', 'current_form'):
            text(data[field], field, error)
        if not isinstance(data['forms'], dict) or data['current_form'] not in data['forms'] or len(data['forms']) > 12:
            raise error('形態清單必須包含目前形態')
        for key, value in data['forms'].items():
            text(key, '形態 ID', error); text(value, '形態描述', error)
        canon['actors'][data['actor']] = {k: copy.deepcopy(data[k]) for k in ('species', 'role', 'forms', 'current_form')}
        canon['actors'][data['actor']].update(source=source, established_revision=revision, powers=[])
    elif kind == 'form':
        if set(data) != {'kind', 'actor', 'id', 'description'}:
            raise error('新形態需要 kind、actor、id、description')
        for field in ('actor', 'id', 'description'):
            text(data[field], field, error)
        record = canon['actors'].get(data['actor'])
        if not record or data['id'] in record['forms']:
            raise error('人物未建立或該形態已存在；不能覆寫')
        record['forms'][data['id']] = data['description']
        canon.setdefault('form_sources', {})[data['actor'] + ':' + data['id']] = {'source': source, 'established_revision': revision}
    elif kind == 'power':
        if set(data) != {'kind', 'id', 'actor', 'name', 'effect', 'requires_flags', 'result_form'}:
            raise error('能力需要 kind、id、actor、name、effect、requires_flags、result_form')
        for field in ('id', 'actor', 'name', 'effect'):
            text(data[field], field, error)
        if data['id'] in canon['powers'] or data['id'] in state['abilities']:
            raise error('能力已建立，不可覆寫來源與效果')
        record = canon['actors'].get(data['actor'])
        if not record:
            raise error('先建立能力擁有人的身分')
        flags = data['requires_flags']
        if not isinstance(flags, list) or len(flags) > 12 or any(not isinstance(f, str) or f not in canon['flags'] for f in flags):
            raise error('能力條件只能引用先前已登記的旗標')
        if data['result_form'] is not None and data['result_form'] not in record['forms']:
            raise error('變身目的形態必須在人物身分建立時已登記')
        rule = {k: copy.deepcopy(v) for k, v in data.items() if k not in {'kind', 'id'}}
        rule.update(source=source, established_revision=revision)
        canon['powers'][data['id']] = rule
        record['powers'].append(data['id'])
        if data['actor'] == state['pc']['id']:
            state['pc']['spells'].append(data['id'])
            state['abilities'][data['id']] = {'name': data['name'], 'effect': data['effect'], 'source': source}
    elif kind == 'flag':
        if set(data) != {'kind', 'id', 'value'} or type(data['value']) is not bool:
            raise error('觸發條件需要 kind、id、value（布林值）')
        text(data['id'], '條件 ID', error)
        canon['flags'][data['id']] = {'value': data['value'], 'source': source, 'established_revision': revision}
    else:
        raise error('世界建立只接受 identity、form、power 或 flag')


def scoped_canon(state, actor_ids):
    canon = copy.deepcopy(state['canon'])
    canon['actors'] = {k: v for k, v in canon['actors'].items() if k in actor_ids}
    canon['powers'] = {k: v for k, v in canon['powers'].items() if v['actor'] in actor_ids}
    canon['uses'] = [u for u in canon['uses'] if u['actor'] in actor_ids and u['target'] in actor_ids][-6:]
    relevant_flags = {f for p in canon['powers'].values() for f in p['requires_flags']}
    canon['flags'] = {k: v for k, v in canon['flags'].items() if k in relevant_flags}
    if 'form_sources' in canon:
        canon['form_sources'] = {k: v for k, v in canon['form_sources'].items() if k.split(':', 1)[0] in actor_ids}
    return canon


def validate_audit(state, proposal, audit, error, action=None):
    if 'canon' not in state:
        return
    if not isinstance(audit, dict) or audit.get('proposal_hash') != digest(proposal) or audit.get('revision') != state['revision']:
        raise error('缺少對這份草案及目前世界版本的敘事核對；不能接受')
    verdict = audit.get('result')
    if not isinstance(verdict, dict) or set(verdict) != {'supported', 'actors', 'powers', 'issues'}:
        raise error('敘事核對資料不完整；世界未變')
    if verdict['supported'] is not True or verdict['issues'] != []:
        raise error('敘事核對未通過；草案含無依據的設定或仍需釐清')
    actors = verdict['actors']
    from .references import audit_actor_ids
    available = set(audit_actor_ids(state, action))
    if not isinstance(actors, list) or not actors or any(not isinstance(a, str) or a not in state['canon']['actors'] or a not in available for a in actors):
        raise error('敘事核對回傳了不屬於本次場景或已知提及人物的 ID；世界未變。')
    powers = verdict['powers']
    expected = [{'actor': e['actor'], 'power': e['power'], 'target': e['target']}
                for e in proposal['events'] if e['type'] == 'power_use']
    if powers != expected:
        raise error('敘事中的超自然效果與引擎核准的能力事件不符')
