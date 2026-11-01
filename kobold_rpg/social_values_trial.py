"""Isolated social-value experiment; declarative contracts, no AI-authored code.

AI selects an existing interaction contract and factor IDs. The host enforces
mandatory factors, knowledge gates and hard boundaries before any dice roll.
"""
import copy
import json
import re

from .context_budget import budget, count
from .engine import RuleError, require_text
from .model import _complete, parse_proposal
from .structured_state_trial import compile_action, validate_values


SELECTION_SCHEMA={'type':'object','properties':{
    'contract_id':{'anyOf':[{'type':'string'},{'type':'null'}]},
    'selected_factor_ids':{'type':'array','maxItems':12,'items':{'type':'string'}}},
    'required':['contract_id','selected_factor_ids'],'additionalProperties':False}


def validate_social(state):
    validate_values(state)
    contracts=state.get('world',{}).get('social_contracts',{})
    if not isinstance(contracts,dict):raise RuleError('社交互動規則格式錯誤。')
    for npc_id,npc in state['npcs'].items():
        social=npc.get('social_state')
        if social is None:continue
        if (not isinstance(social,dict) or set(social)!={'values','value_sources','knowledge','boundaries','boundary_sources'} or
                not isinstance(social['values'],dict) or not isinstance(social['value_sources'],dict) or
                not isinstance(social['knowledge'],dict) or not isinstance(social['boundaries'],dict) or
                not isinstance(social['boundary_sources'],dict)):
            raise RuleError('人物社交狀態格式錯誤。')
        for key,value in social['values'].items():
            source=social['value_sources'].get(key)
            if (not isinstance(key,str) or type(value) is not int or not 0<=value<=10 or
                    not isinstance(source,dict) or type(source.get('revision')) is not int or
                    not isinstance(source.get('source'),str) or not source['source']):
                raise RuleError('人物數值或來源無效。')
        for fact_id,fact in social['knowledge'].items():
            if (not isinstance(fact_id,str) or not isinstance(fact,dict) or
                    type(fact.get('known')) is not bool or
                    not isinstance(fact.get('source'),str) or not fact['source'] or
                    type(fact.get('revision')) is not int or
                    (fact['known'] and not isinstance(fact.get('text'),str))):
                raise RuleError('人物所知事實格式錯誤。')
        for boundary_id,active in social['boundaries'].items():
            record=social['boundary_sources'].get(boundary_id)
            if (not isinstance(boundary_id,str) or type(active) is not bool or
                    not isinstance(record,dict) or type(record.get('revision')) is not int or
                    not isinstance(record.get('source'),str) or not record['source']):
                raise RuleError('人物底線格式錯誤。')
    for contract_id,rule in contracts.items():
        if (not isinstance(contract_id,str) or not re.fullmatch(r'[a-z][a-z0-9_]{2,63}',contract_id) or
                not isinstance(rule,dict) or
                set(rule)!={'npc_id','label','base_dc','factors','gate','effect','responses','source_revision','source'} or
                rule['npc_id'] not in state['npcs'] or
                not isinstance(rule['label'],str) or not rule['label'].strip() or
                type(rule['base_dc']) is not int or not 2<=rule['base_dc']<=25 or
                type(rule['source_revision']) is not int or
                not isinstance(rule['source'],str) or not rule['source'] or
                not isinstance(rule['factors'],list) or len(rule['factors'])>12):
            raise RuleError('社交互動規則不完整。')
        social=state['npcs'][rule['npc_id']].get('social_state')
        if social is None:raise RuleError('社交規則所指人物沒有數值狀態。')
        seen=set()
        for factor in rule['factors']:
            if (not isinstance(factor,dict) or set(factor)!={'id','direction','weight','mandatory'} or
                    factor['id'] not in social['values'] or factor['id'] in seen or
                    factor['direction'] not in ('support','resist') or
                    type(factor['weight']) is not int or not 1<=factor['weight']<=2 or
                    type(factor['mandatory']) is not bool):
                raise RuleError('社交因素引用無效。')
            seen.add(factor['id'])
        gate=rule['gate']
        if gate is not None and (not isinstance(gate,dict) or set(gate)!={'kind','id','expected'} or
                type(gate['expected']) is not bool or
                (gate['kind']=='knowledge' and gate['id'] not in social['knowledge']) or
                (gate['kind']=='boundary' and gate['id'] not in social['boundaries']) or
                gate['kind'] not in ('knowledge','boundary')):
            raise RuleError('社交前提引用無效。')
        effect=rule['effect']
        if (not isinstance(effect,dict) or set(effect)!={'kind','key'} or
                effect['kind'] not in ('permission','share_fact','agreement') or
                not isinstance(effect['key'],str) or
                (effect['kind']=='share_fact' and effect['key'] not in social['knowledge'])):
            raise RuleError('社交結果格式無效。')
        responses=rule['responses']
        if (not isinstance(responses,dict) or set(responses)!={'blocked','refused','succeeded'} or
                any(not isinstance(value,str) or not value.strip() or len(value)>240
                    for value in responses.values())):
            raise RuleError('社交回應格式無效。')
    return contracts


def register_social_contract(state,contract_id,definition):
    """Stage a new data-only interaction rule; never evaluate AI-authored code."""
    if contract_id in state.get('world',{}).get('social_contracts',{}):
        raise RuleError('社交互動規則已存在。')
    candidate=copy.deepcopy(state)
    candidate.setdefault('world',{}).setdefault('social_contracts',{})[contract_id]=copy.deepcopy(definition)
    validate_social(candidate)
    return candidate


def apply_social_event(state,npc_id,event_id,source,*,deltas=None,
                       knowledge_updates=None,boundary_updates=None):
    """Apply an already established event to values; preserve source/order.

    This function does not decide whether an event actually happened. Its
    caller must supply an authoritative event, never a player's mere claim.
    """
    validate_social(state)
    if (npc_id not in state['npcs'] or 'social_state' not in state['npcs'][npc_id] or
            not isinstance(event_id,str) or not re.fullmatch(r'[a-z][a-z0-9_]{2,63}',event_id) or
            not isinstance(source,str) or not source.strip() or
            event_id in state.get('world',{}).get('social_value_events',{})):
        raise RuleError('社交事件來源或識別無效。')
    deltas=deltas or {};knowledge_updates=knowledge_updates or {};boundary_updates=boundary_updates or {}
    if not all(isinstance(item,dict) for item in (deltas,knowledge_updates,boundary_updates)):
        raise RuleError('社交事件更新格式無效。')
    candidate=copy.deepcopy(state)
    social=candidate['npcs'][npc_id]['social_state'];revision=state['revision']+1
    record={'revision':revision,'source':source}
    for key,delta in deltas.items():
        if key not in social['values'] or type(delta) is not int or not -3<=delta<=3:
            raise RuleError('社交事件不能任意創造數值或大幅改寫人物。')
        social['values'][key]=max(0,min(10,social['values'][key]+delta))
        social['value_sources'][key]=record
    for key,fact in knowledge_updates.items():
        if (not isinstance(key,str) or not isinstance(fact,dict) or
                set(fact)!={'known','text'} or type(fact['known']) is not bool or
                not isinstance(fact['text'],str) or
                (fact['known'] and not fact['text'].strip())):
            raise RuleError('人物新知識格式無效。')
        social['knowledge'][key]={**fact,**record}
    for key,active in boundary_updates.items():
        if key not in social['boundaries'] or type(active) is not bool:
            raise RuleError('社交事件不能新增未建立底線。')
        social['boundaries'][key]=active
        social['boundary_sources'][key]=record
    candidate['world'].setdefault('social_value_events',{})[event_id]={
        'npc_id':npc_id,**record,'deltas':deltas,
        'knowledge_updates':knowledge_updates,'boundary_updates':boundary_updates}
    validate_social(candidate)
    return candidate


def select_social_context(state,npc_id,text,base_url,complete=None):
    """AI chooses relevant established values; host checks and adds required ones."""
    complete=complete or _complete
    contracts=validate_social(state)
    npc=state['npcs'].get(npc_id)
    if not npc or npc['location']!=state['pc']['location'] or 'social_state' not in npc:
        raise RuleError('目前沒有可互動的已建立人物。')
    available={key:{'label':rule['label'],
                    'factor_ids':[row['id'] for row in rule['factors']]}
               for key,rule in contracts.items() if rule['npc_id']==npc_id}
    relevant_ids={factor for rule in available.values() for factor in rule['factor_ids']}
    payload={'request':text,'npc_id':npc_id,'npc_name':npc['name'],
             'values':{key:value for key,value in npc['social_state']['values'].items()
                       if key in relevant_ids},'contracts':available}
    instruction=('只識別這次請求對應的已登記 contract_id，並從該規則的 factor_ids 揀相關數值 ID。'
                 '不要決定成功、擲骰或編造新因素。玩家的承諾不等於已證實事實。'
                 '沒有合適規則時 contract_id=null。只回 JSON。')
    messages=[{'role':'system','content':instruction+'\n'+
               json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]
    measured=count(base_url,messages);limit=budget(base_url,300)
    if limit and measured is not None and measured>limit:
        raise RuleError('社交判斷超過模型容量，故事未執行。')
    raw=complete(messages,base_url,300,.1,response_schema=SELECTION_SCHEMA,raw=True)
    choice=parse_proposal(raw) if isinstance(raw,str) else raw
    if (not isinstance(choice,dict) or set(choice)!=set(SELECTION_SCHEMA['required']) or
            choice['contract_id'] is not None and choice['contract_id'] not in available or
            not isinstance(choice['selected_factor_ids'],list) or
            len(choice['selected_factor_ids'])>12 or
            any(not isinstance(item,str) for item in choice['selected_factor_ids']) or
            len(choice['selected_factor_ids'])!=len(set(choice['selected_factor_ids']))):
        raise RuleError('社交因素選擇格式無效。')
    if choice['contract_id'] is not None:
        allowed=set(available[choice['contract_id']]['factor_ids'])
        if not set(choice['selected_factor_ids'])<=allowed:
            raise RuleError('社交因素選擇了無關數值。')
    elif choice['selected_factor_ids']:
        raise RuleError('沒有規則時不能挑選因素。')
    return choice,measured


def resolve_social(state,npc_id,choice,roller=None):
    """Calculate a candidate decision. No writes and no semantic claim creation."""
    import secrets
    contracts=validate_social(state)
    if choice['contract_id'] is None:
        return {'status':'unresolved','reason':'沒有已登記的社交互動規則',
                'npc_id':npc_id,'changes':{},'rolls':[],'factors':[]}
    rule=contracts[choice['contract_id']]
    if rule['npc_id']!=npc_id:raise RuleError('社交規則不屬於目前人物。')
    npc=state['npcs'][npc_id]
    if npc['location']!=state['pc']['location']:
        raise RuleError('互動人物不在目前地點。')
    social=npc['social_state'];gate=rule['gate']
    if gate is not None:
        actual=(social['knowledge'][gate['id']]['known'] if gate['kind']=='knowledge'
                else social['boundaries'][gate['id']])
        if actual is not gate['expected']:
            return {'status':'blocked','contract_id':choice['contract_id'],
                    'npc_id':npc_id,
                    'reason':f'{gate["kind"]}:{gate["id"]} 不符合已建立前提',
                    'changes':{},'rolls':[],'factors':[]}
    selected=set(choice['selected_factor_ids'])
    factors=[]
    for item in rule['factors']:
        if not item['mandatory'] and item['id'] not in selected:continue
        value=social['values'][item['id']]
        impact=(value-5)*item['weight']*(1 if item['direction']=='resist' else -1)
        factors.append({'id':item['id'],'value':value,'impact':impact,
                        'source':social['value_sources'][item['id']]})
    dc=max(2,min(30,rule['base_dc']+sum(item['impact'] for item in factors)))
    roller=roller or (lambda sides:secrets.randbelow(sides)+1)
    die=roller(20)
    if type(die) is not int or not 1<=die<=20:raise RuleError('骰子數值無效。')
    skill_bonus=2 if '交涉' in state['pc']['capabilities'] else 0
    total=die+skill_bonus;success=total>=dc
    roll={'die':die,'skill_bonus':skill_bonus,'base_dc':rule['base_dc'],
          'target':dc,'total':total,'success':success}
    changes={}
    if success and rule['effect']['kind']=='permission':
        key=rule['effect']['key']
        changes={'world':{'permissions':{key:{'npc_id':npc_id,'granted':True,
            'revision':state['revision']+1,'source_contract':choice['contract_id']}}}}
    if success and rule['effect']['kind']=='agreement':
        key=rule['effect']['key']
        changes={'world':{'social_agreements':{key:{'npc_id':npc_id,
            'actor_id':state['pc']['id'],'agreed':True,'revision':state['revision']+1,
            'source_contract':choice['contract_id']}}}}
    if success and rule['effect']['kind']=='share_fact':
        fact=social['knowledge'][rule['effect']['key']]
        if not fact['known']:
            return {'status':'blocked','contract_id':choice['contract_id'],
                    'npc_id':npc_id,
                    'reason':'人物不知道此事','changes':{},'rolls':[],
                    'factors':factors}
    return {'status':'succeeded' if success else 'refused',
            'contract_id':choice['contract_id'],'npc_id':npc_id,
            'effect':rule['effect'],'changes':changes,'rolls':[roll],
            'factors':factors,'selected_factor_ids':choice['selected_factor_ids']}


def render_social(state,text,decision):
    npc=state['npcs'][decision['npc_id']]['name']
    if decision['status']=='unresolved':return '這個請求尚無可用的互動規則，不能直接判定對方同意。'
    rule=state['world']['social_contracts'][decision['contract_id']]
    if decision['status']=='blocked':return rule['responses']['blocked']
    if decision['status']=='refused':return rule['responses']['refused']
    effect=decision['effect']
    if effect['kind'] in ('permission','agreement'):return rule['responses']['succeeded']
    fact=state['npcs'][decision['npc_id']]['social_state']['knowledge'][effect['key']]
    return f'{npc}告訴你：{fact["text"]}'


def trial_social_turn(state,text,base_url,complete=None,roller=None):
    original=require_text(text,'玩家輸入')
    intent,first=compile_action(state,original,base_url,complete)
    social_steps=[step for step in intent['steps'] if step['action']=='persuade' and not step['negated']]
    if intent['mode']!='play' or len(social_steps)!=1 or len(intent['steps'])!=1:
        raise RuleError('此社交試驗只接受單一明確請求。')
    npc_id=social_steps[0]['target_id']
    choice,second=select_social_context(state,npc_id,original,base_url,complete)
    decision=resolve_social(state,npc_id,choice,roller)
    return {'intent':intent,'choice':choice,'decision':decision,
            'narration':render_social(state,original,decision),
            'input_tokens':[first,second],'output_caps':[450,300]}
