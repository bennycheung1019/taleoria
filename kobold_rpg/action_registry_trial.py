"""Declarative action-rule experiment. No generated code is ever executed.

Only a small set of generic operations is deterministic here. Unresolved
social, combat, physical and fictional judgments remain explicit; a player
declaration never grants a new capability or guarantees success.
"""
import copy
import json
import re
import secrets

from .engine import RuleError


PRIMITIVES = {'observe', 'speak', 'move', 'use_ability', 'custom', 'judgment'}
FLAGS = {'open', 'locked', 'secured', 'damaged', 'active'}
RULE_KEYS = {'id', 'aliases', 'scope', 'operator', 'required_capability',
             'required_item', 'required_flag', 'roll', 'effect', 'basis'}
STEP_KEYS = {'primitive', 'target_id', 'item_id', 'rule_id', 'utterance', 'goal', 'negated', 'difficulty'}


def evidence_sources(state):
    """Stable IDs for existing world evidence; only these may justify DC factors."""
    here=state['pc']['location']
    world=state.get('world',{})
    sources={'pc.capabilities':'、'.join(state['pc']['capabilities']),
             'pc.inventory':json.dumps(state['pc']['inventory'],ensure_ascii=False,sort_keys=True),
             'location:'+here:state['locations'][here]['description']}
    for key,entity in world.get('entities',{}).items():
        if entity.get('location')==here:
            sources['entity:'+key]=json.dumps(entity,ensure_ascii=False,sort_keys=True)
            for name,value in entity.get('flags',{}).items():
                if type(value) is bool:
                    sources[f'entity:{key}.flag.{name}']=f'{entity.get("name",key)} {name}={str(value).lower()}'
    for index,rule in enumerate(world.get('rules',[])):
        if isinstance(rule,str):sources['world.rule:'+str(index)]=rule
    for index,fact in enumerate(state.get('facts',[])):
        if isinstance(fact,dict) and isinstance(fact.get('text'),str):
            sources['fact:'+str(index)]=fact['text']
    for key,npc in state['npcs'].items():
        if npc['location']==here:
            sources['npc:'+key]=npc['description']+' '+json.dumps(npc.get('anchor',{}),ensure_ascii=False)
            for name,value in npc.get('anchor',{}).items():
                if isinstance(value,str) and len(value)<=60:
                    sources[f'npc:{key}.anchor.{name}']=value
    return sources


def validate_difficulty(state, difficulty, rule):
    if (not isinstance(difficulty,dict) or set(difficulty)!={'base','factors','target'} or
            type(difficulty['base']) is not int or difficulty['base']!=10 or
            type(difficulty['target']) is not int or
            not isinstance(difficulty['factors'],list) or len(difficulty['factors'])>3):
        raise RuleError('本回合難度缺少基準、因素或目標值。')
    sources=evidence_sources(state);seen=set();impact=0
    for factor in difficulty['factors']:
        if (not isinstance(factor,dict) or set(factor)!={'source_id','quote','impact','reason'} or
                not isinstance(factor['source_id'],str) or factor['source_id'] not in sources or
                not isinstance(factor['quote'],str) or not factor['quote'] or len(factor['quote'])>60 or
                factor['quote'] not in sources[factor['source_id']] or
                not isinstance(factor['reason'],str) or not factor['reason'].strip() or
                len(factor['reason'])>80 or type(factor['impact']) is not int or
                not -6<=factor['impact']<=6):
            raise RuleError('難度因素須引用已建立資料中的原文。')
        reference=(factor['source_id'],factor['quote'])
        if reference in seen:raise RuleError('同一難度因素不能重複計算。')
        # Base 10 assumes that a rule's mandatory tool/skill is available.
        # Otherwise the same prerequisite is rewarded twice: once to permit
        # the action, then again as a negative DC modifier.
        if factor['impact'] and (
            factor['source_id']=='pc.capabilities' and rule['required_capability'] and
            rule['required_capability'] in factor['quote'] or
            factor['source_id']=='pc.inventory' and rule['required_item'] and
            rule['required_item'] in factor['quote']):
            raise RuleError('規則必需的技能或工具已計入基準難度，不能重複調整。')
        seen.add(reference);impact+=factor['impact']
    target=difficulty['base']+impact
    if target!=difficulty['target'] or not 2<=target<=min(30,rule['roll']['count']*rule['roll']['sides']+rule['roll']['modifier']):
        raise RuleError('難度目標與已列因素或骰制不符。')
    return copy.deepcopy(difficulty)


def rules(state):
    entries = state.get('world', {}).get('action_rules', [])
    if not isinstance(entries, list):
        raise RuleError('動作規則庫格式不正確。')
    return copy.deepcopy(entries)


def validate_definition(state, rule):
    if not isinstance(rule, dict) or set(rule) != RULE_KEYS:
        raise RuleError('新動作規則欄位不完整。')
    key = rule['id']
    if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{2,63}', key):
        raise RuleError('動作規則 ID 格式不正確。')
    if rule['scope'] != state['campaign_id'] or rule['operator'] != 'set_entity_flag':
        raise RuleError('新規則必須限於目前世界的受控動作。')
    if not isinstance(rule['aliases'], list) or not rule['aliases'] or len(rule['aliases']) > 8 or any(
            not isinstance(alias, str) or not alias.strip() or len(alias) > 80 for alias in rule['aliases']):
        raise RuleError('動作名稱不正確。')
    if any(not isinstance(rule[field], str) or len(rule[field]) > 300
           for field in ('required_capability', 'required_item', 'basis')) or not rule['basis'].strip():
        raise RuleError('規則前提或依據不正確。')
    if not (rule['required_capability'] or rule['required_item']):
        raise RuleError('新規則須依賴本回合前已有的能力或工具，不能憑宣告自授。')
    before = rule['required_flag']; effect = rule['effect']; roll = rule['roll']
    if (not isinstance(before, dict) or set(before) != {'name', 'value'} or
            before['name'] not in FLAGS or type(before['value']) is not bool or
            not isinstance(effect, dict) or set(effect) != {'name', 'value'} or
            effect['name'] not in FLAGS or type(effect['value']) is not bool):
        raise RuleError('新規則只可更改已登記物件的布林狀態。')
    if (not isinstance(roll, dict) or set(roll) != {'count', 'sides', 'modifier', 'target'} or
            any(type(roll[field]) is not int for field in roll) or
            not 1 <= roll['count'] <= 3 or not 2 <= roll['sides'] <= 100 or
            not -10 <= roll['modifier'] <= 10 or
            not 2 <= roll['target'] <= roll['count'] * roll['sides'] + roll['modifier']):
        raise RuleError('新規則必須提供有界的擲骰裁定。')
    for existing in rules(state):
        if existing['id'] == key or set(existing['aliases']) & set(rule['aliases']):
            raise RuleError('動作規則已存在或名稱互相衝突。')
    return copy.deepcopy(rule)


def validate_intent(intent):
    if not isinstance(intent, dict) or set(intent) != {'mode', 'steps', 'new_rule'}:
        raise RuleError('行動意圖格式不完整。')
    if intent['mode'] not in ('play', 'ooc') or not isinstance(intent['steps'], list) or len(intent['steps']) > 4:
        raise RuleError('行動類型或步驟不正確。')
    if intent['mode'] == 'ooc' and (intent['steps'] or intent['new_rule'] is not None):
        raise RuleError('OOC 不可當成遊戲動作或新增規則。')
    if intent['mode'] == 'play' and not intent['steps']:
        raise RuleError('玩家行動缺少步驟。')
    for step in intent['steps']:
        if not isinstance(step, dict) or set(step) != STEP_KEYS or step['primitive'] not in PRIMITIVES:
            raise RuleError('行動步驟格式不正確。')
        if any(value is not None and not isinstance(value, str) for key, value in step.items()
               if key not in ('primitive', 'negated', 'difficulty')) or type(step['negated']) is not bool:
            raise RuleError('行動參數格式不正確。')
        if step['difficulty'] is not None and not isinstance(step['difficulty'],dict):
            raise RuleError('難度格式不正確。')
    if intent['new_rule'] is not None and not isinstance(intent['new_rule'], dict):
        raise RuleError('新動作規則格式不正確。')
    return copy.deepcopy(intent)


def resolve(state, intent, roller=None):
    """Calculate a candidate delta. Caller commits only after narration succeeds.

    `roller(sides)` supplies one die result in [1,sides]. The returned record
    carries the actual rolls so retries can reuse it rather than rerolling.
    """
    intent = validate_intent(intent)
    if intent['mode'] == 'ooc':
        return {'status': 'ooc', 'steps': [], 'changes': {}, 'rolls': [], 'new_rule': None}
    roller = roller or (lambda sides: secrets.randbelow(sides) + 1)
    candidate = copy.deepcopy(state)
    fresh = validate_definition(state, intent['new_rule']) if intent['new_rule'] is not None else None
    if fresh and not any(step['primitive']=='custom' and step['rule_id']==fresh['id']
                         and not step['negated'] for step in intent['steps']):
        raise RuleError('新規則必須對應玩家實際嘗試的動作。')
    catalog = {entry['id']: entry for entry in rules(state)}
    if fresh:
        catalog[fresh['id']] = fresh
    outcomes=[];rolls=[];used_fresh=False
    for step in intent['steps']:
        primitive=step['primitive']; target=step['target_id']
        if step['negated']:
            outcomes.append({'primitive': primitive, 'status': 'not_attempted', 'reason': '玩家明確否定此動作'})
            continue
        if primitive == 'observe':
            outcomes.append({'primitive': primitive, 'status': 'perception', 'reason': '只提供視角可感知資料，未宣告搜索成功'})
        elif primitive == 'speak':
            outcomes.append({'primitive': primitive, 'status': 'spoken',
                             'utterance': step['utterance'] or '',
                             'reason': '台詞已說出；對方是否同意仍待其自主反應'})
        elif primitive == 'move':
            exits=candidate['locations'][candidate['pc']['location']]['exits']
            route=exits.get(target)
            if route and route.get('known') is True and route.get('clear') is True:
                candidate['pc']['location']=target
                outcomes.append({'primitive': primitive, 'status': 'succeeded', 'destination': target})
            else:
                outcomes.append({'primitive': primitive, 'status': 'unresolved', 'reason': '沒有已確認可通行路線'})
        elif primitive == 'use_ability':
            from .ability_sources import source_for
            source=source_for(state, step['rule_id'])
            outcomes.append({'primitive': primitive, 'status': 'unresolved' if source else 'no_effect',
                             'reason': '需依已建立能力效果裁定' if source else '本回合前沒有能力來源'})
        elif primitive == 'custom':
            rule=catalog.get(step['rule_id'])
            if not rule:
                outcomes.append({'primitive': primitive, 'status': 'unresolved', 'reason': '沒有適用的受控規則'})
                continue
            entity=candidate.get('world', {}).get('entities', {}).get(target)
            if not isinstance(entity, dict) or entity.get('location') != candidate['pc']['location']:
                outcomes.append({'primitive': primitive, 'status': 'unresolved', 'reason': '目標物件未在目前地點建立'})
                continue
            if (rule['required_capability'] and rule['required_capability'] not in state['pc']['capabilities'] or
                    rule['required_item'] and state['pc']['inventory'].get(rule['required_item'],0)<1):
                outcomes.append({'primitive': primitive, 'status': 'no_effect', 'reason': '欠缺事前已建立的能力或工具'})
                continue
            before=rule['required_flag']
            if entity.get('flags',{}).get(before['name']) is not before['value']:
                outcomes.append({'primitive': primitive, 'status': 'unresolved', 'reason': '物件狀態不符合規則前提'})
                continue
            if fresh and rule['id']==fresh['id']:
                used_fresh=True
            die=rule['roll']
            difficulty=validate_difficulty(state,step['difficulty'],rule) if step['difficulty'] is not None else None
            target_dc=difficulty['target'] if difficulty else die['target']
            values=[roller(die['sides']) for _ in range(die['count'])]
            if any(type(value) is not int or not 1<=value<=die['sides'] for value in values):
                raise RuleError('擲骰來源回傳無效數字。')
            total=sum(values)+die['modifier'];success=total>=target_dc
            rolls.append({'rule_id':rule['id'],'target_id':target,'dice':values,'modifier':die['modifier'],
                          'target':target_dc,'difficulty':difficulty,
                          'difficulty_policy':'base10-required-prerequisites-v1',
                          'total':total,'success':success})
            if success:
                effect=rule['effect']
                entity.setdefault('flags',{})[effect['name']]=effect['value']
            outcomes.append({'primitive': primitive, 'status': 'succeeded' if success else 'failed',
                             'rule_id':rule['id'],'target_id':target})
        else:
            outcomes.append({'primitive': primitive, 'status': 'unresolved',
                             'reason': '此自由行動尚無通用程式裁定，須由主持依世界事實判斷'})
    changes={}
    if candidate['pc'] != state['pc']:
        changes['pc']={'location':candidate['pc']['location']}
    world_before=state.get('world',{})
    world_after=candidate.get('world',{})
    world_patch={}
    if world_after.get('entities') != world_before.get('entities'):
        world_patch['entities']=world_after.get('entities',{})
    if fresh and used_fresh:
        world_patch['action_rules']=[*rules(state),{**fresh,'source_revision':state['revision']+1}]
    if world_patch:
        changes['world']=world_patch
    return {'status':'resolved' if all(row['status'] not in ('unresolved','spoken') for row in outcomes) else 'needs_judgment',
            'steps':outcomes,'changes':changes,'rolls':rolls,'new_rule':fresh}
