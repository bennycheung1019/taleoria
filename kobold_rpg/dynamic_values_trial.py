"""Data-only expansion of NPC/object values from established evidence.

Unknown actions may propose bounded attributes and one supported dice/set
operator. No model-authored source code or player assertion becomes a fact.
"""
import copy
import json
import re

from .context_budget import budget, count
from .engine import RuleError, require_text
from .model import _complete, parse_proposal
from .structured_state_trial import ACTIONS,compile_action,resolve_values,validate_values
from .social_values_trial import validate_social


SLUG=re.compile(r'[a-z][a-z0-9_]{2,63}')
ATTRIBUTE_SCHEMA={'type':'object','properties':{
    'id':{'type':'string'},'label':{'type':'string'},
    'value':{'type':'integer','minimum':2,'maximum':30},
    'source_quote':{'type':'string'},'reason':{'type':'string'}},
    'required':['id','label','value','source_quote','reason'],'additionalProperties':False}
OBJECT_PROPOSAL_SCHEMA={'type':'object','properties':{
    'action_id':{'type':'string'},'label':{'type':'string'},
    'target_id':{'type':'string'},'target_type':{'type':'string'},
    'difficulty':ATTRIBUTE_SCHEMA,
    'effect':{'type':'object','properties':{
        'id':{'type':'string'},'label':{'type':'string'},
        'initial':{'type':'boolean'},'on_success':{'type':'boolean'},
        'source_quote':{'type':'string'},'reason':{'type':'string'}},
        'required':['id','label','initial','on_success','source_quote','reason'],
        'additionalProperties':False},
    'operator':{'type':'string','enum':['check_and_set_boolean']}},
    'required':['action_id','label','target_id','target_type','difficulty','effect','operator'],
    'additionalProperties':False}
SOCIAL_PROPOSAL_SCHEMA={'type':'object','properties':{
    'kind':{'type':'string','enum':['emotion','priority','trait','need','relation']},
    'label':{'type':'string'},
    'initial_value':{'type':'integer','minimum':0,'maximum':10},
    'source_quote':{'type':'string'},'reason':{'type':'string'},
    'effects':{'type':'array','maxItems':4,'items':{'type':'object','properties':{
        'contract_id':{'type':'string'},'direction':{'type':'string','enum':['support','resist']},
        'weight':{'type':'integer','minimum':1,'maximum':2}},
        'required':['contract_id','direction','weight'],'additionalProperties':False}}},
    'required':['kind','label','initial_value','source_quote','reason','effects'],
    'additionalProperties':False}


def _text(value):
    return isinstance(value,str) and 1<=len(value.strip())<=240


def object_evidence(state,target_id):
    entity=state.get('world',{}).get('entities',{}).get(target_id)
    if not entity or entity.get('location')!=state['pc']['location']:
        raise RuleError('新動作目標並非目前已建立物件。')
    here=state['pc']['location']
    # A room description is evidence about this object only if it names it.
    # Otherwise, rain, another door, etc. could be quoted as its hardness.
    name=entity.get('name','')
    def target_sentences(source):
        if not isinstance(source,str):return ''
        return ''.join(sentence for sentence in re.split(r'(?<=[。！？.!?])',source)
                       if ((isinstance(name,str) and bool(name) and name in sentence) or
                           target_id in sentence))
    place=state['locations'][here]['description']
    evidence={'object_description':entity.get('description',''),
              'place_description':target_sentences(place)}
    evidence.update({f'fact:{i}':target_sentences(fact['text'])
                     for i,fact in enumerate(state.get('facts',[]))
                     if isinstance(fact,dict) and isinstance(fact.get('text'),str) and
                     fact.get('visibility')=='public'})
    return {key:value for key,value in evidence.items() if value}


def register_object_extension(state,proposal):
    """Stage typed fields and one operator, with pre-turn narrative citations."""
    validate_values(state)
    if not isinstance(proposal,dict) or set(proposal)!=set(OBJECT_PROPOSAL_SCHEMA['required']):
        raise RuleError('新動作資料不完整。')
    action=proposal['action_id'];target=proposal['target_id']
    difficulty=proposal['difficulty'];effect=proposal['effect']
    if isinstance(difficulty,dict) and isinstance(effect,dict) and action in (difficulty.get('id'),effect.get('id')):
        action=f'action_{state["revision"]+1}_{len(state.get("world",{}).get("dynamic_actions",{}))+1}'
    entity=state.get('world',{}).get('entities',{}).get(target)
    if (not isinstance(action,str) or not SLUG.fullmatch(action) or
            action in ACTIONS or action in state.get('world',{}).get('dynamic_actions',{}) or
            not isinstance(entity,dict) or entity.get('location')!=state['pc']['location'] or
            proposal['target_type']!=entity.get('type') or
            proposal['operator']!='check_and_set_boolean' or not _text(proposal['label'])):
        raise RuleError('新動作識別、目標或操作不受支援。')
    if (not isinstance(difficulty,dict) or set(difficulty)!=set(ATTRIBUTE_SCHEMA['required']) or
            not isinstance(effect,dict) or set(effect)!=set(OBJECT_PROPOSAL_SCHEMA['properties']['effect']['required'])):
        raise RuleError('新物件屬性格式不完整。')
    ids=[difficulty['id'],effect['id']]
    if (any(not isinstance(key,str) or not SLUG.fullmatch(key) for key in ids) or
            len(set(ids))!=2 or any(key in entity['values'] for key in ids) or
            type(difficulty['value']) is not int or not 2<=difficulty['value']<=30 or
            type(effect['initial']) is not bool or type(effect['on_success']) is not bool or
            effect['initial'] is effect['on_success'] or
            any(not _text(item['label']) or not _text(item['reason']) or
                    not _text(item['source_quote']) or len(item['source_quote'].strip())<4
                    for item in (difficulty,effect))):
        raise RuleError('新屬性名稱、數值或狀態變化無效。')
    evidence=object_evidence(state,target)
    for item in (difficulty,effect):
        if not any(item['source_quote'] in source for source in evidence.values()):
            raise RuleError('新屬性沒有引用本回合前的已建立敘事。')
    result=copy.deepcopy(state);world=result.setdefault('world',{})
    defs=world.setdefault('attribute_definitions',{});actions=world.setdefault('dynamic_actions',{})
    for item,kind,minimum,maximum,value in ((difficulty,'int',2,30,difficulty['value']),
                                             (effect,'bool',None,None,effect['initial'])):
        definition_id=f'{proposal["target_type"]}.{item["id"]}'
        if definition_id in defs:raise RuleError('新屬性與既有定義重複。')
        defs[definition_id]={'kind':kind,'min':minimum,'max':maximum,
            'label':item['label'],'source_quote':item['source_quote'],
            'reason':(f'AI 建議初始難度 {value}；具體數值尚未由物理規則獨立校準。'
                      if kind=='int' else
                      f'成功後只設定 {item["id"]}={str(effect["on_success"]).lower()}；其他狀態不變。'),
            'source_revision':state['revision']+1}
        world['entities'][target]['values'][item['id']]=value
        world['entities'][target]['value_sources'][item['id']]={
            'revision':state['revision']+1,'source':item['source_quote']}
    actions[action]={'target_type':proposal['target_type'],
        'difficulty_attribute':difficulty['id'],'effect_attribute':effect['id'],
        'effect_value':effect['on_success'],'operator':'check_and_set_boolean',
        'label':proposal['label'],'source_revision':state['revision']+1}
    validate_values(result)
    return result


def propose_object_extension(state,text,target_id,base_url,complete=None,repair=None):
    complete=complete or _complete
    original=require_text(text,'玩家輸入')
    entity=state.get('world',{}).get('entities',{}).get(target_id)
    evidence=object_evidence(state,target_id)
    payload={'action':original,'target_id':target_id,'target_type':entity['type'],
             'current_values':entity['values'],'established_evidence':evidence}
    instruction=('只提出一個資料型新動作：一個 2–30 的難度整數屬性、一個布林結果屬性，'
                 '以及 check_and_set_boolean 操作。ID 用英文小寫底線。'
                 '例如破門可用 breach_dc 和 breached；擲骰成功只更改 breached，'
                 '不得自動改 open、locked 或賦予玩家能力。'
                 'effect.initial 必須與 effect.on_success 不同；如果已建立證據說門未有破口，'
                 'breached 初始值必須是 false。'
                 '每個 source_quote 必須逐字出自 established_evidence，不可引用玩家希望或宣告。'
                 '未知強度不要假扮成已知事實；只回 JSON。')
    messages=[{'role':'system','content':instruction+'\n'+
               json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]
    if repair is not None:
        previous,error=repair
        messages.append({'role':'user','content':
            '上次提案未通過程式驗證。只修正錯誤並重新輸出完整 JSON。'
            +json.dumps({'error':error,'previous_proposal':previous},
                        ensure_ascii=False,separators=(',',':'))})
    measured=count(base_url,messages);limit=budget(base_url,500)
    if limit and measured is not None and measured>limit:
        raise RuleError('新動作提案超過模型容量，故事未執行。')
    raw=complete(messages,base_url,500,.15,response_schema=OBJECT_PROPOSAL_SCHEMA,raw=True)
    proposal=parse_proposal(raw) if isinstance(raw,str) else raw
    return proposal,measured


def register_npc_attribute(state,npc_id,event_id,proposal):
    """Add one sourced social dimension and bounded contract factors."""
    validate_social(state)
    event=state.get('world',{}).get('confirmed_events',{}).get(event_id)
    if (not isinstance(event,dict) or npc_id not in event.get('participants',[]) or
            type(event.get('revision')) is not int or not 0<=event['revision']<=state['revision'] or
            not isinstance(event.get('text'),str) or
            not isinstance(proposal,dict) or set(proposal)!=set(SOCIAL_PROPOSAL_SCHEMA['required'])):
        raise RuleError('新人物數值需要涉及該人物的已確認事件。')
    npc=state['npcs'][npc_id];social=npc.get('social_state')
    if not isinstance(social,dict):raise RuleError('人物未有可擴充的社交狀態。')
    kind=proposal['kind']
    key=f'{kind}.event_{state["revision"]+1}_{len(state["world"].get("social_attribute_definitions",{}))+1}'
    if (kind not in ('emotion','priority','trait','need','relation') or
            key in social['values'] or type(proposal['initial_value']) is not int or
            not 0<=proposal['initial_value']<=10 or
            not _text(proposal['label']) or not _text(proposal['reason']) or
            not _text(proposal['source_quote']) or proposal['source_quote'] not in event['text'] or
            not isinstance(proposal['effects'],list) or len(proposal['effects'])>4):
        raise RuleError('新人物屬性或證據無效。')
    seen=set()
    for item in proposal['effects']:
        if (not isinstance(item,dict) or set(item)!={'contract_id','direction','weight'} or
                item['contract_id'] in seen or item['contract_id'] not in state['world'].get('social_contracts',{}) or
                state['world']['social_contracts'][item['contract_id']]['npc_id']!=npc_id or
                item['direction'] not in ('support','resist') or
                type(item['weight']) is not int or not 1<=item['weight']<=2):
            raise RuleError('新人物屬性的規則連結無效。')
        seen.add(item['contract_id'])
    result=copy.deepcopy(state);social=result['npcs'][npc_id]['social_state']
    revision=state['revision']+1
    social['values'][key]=proposal['initial_value']
    social['value_sources'][key]={'revision':revision,'source':event_id+':'+proposal['source_quote']}
    result['world'].setdefault('social_attribute_definitions',{})[key]={
        'label':proposal['label'],'reason':proposal['reason'],
        'source_event':event_id,'source_quote':proposal['source_quote'],
        'source_revision':revision,'npc_id':npc_id}
    for item in proposal['effects']:
        rule=result['world']['social_contracts'][item['contract_id']]
        rule['factors'].append({'id':key,'direction':item['direction'],
                                'weight':item['weight'],'mandatory':True})
    validate_social(result)
    return result


def propose_npc_attribute(state,npc_id,event_id,base_url,complete=None):
    complete=complete or _complete
    event=state.get('world',{}).get('confirmed_events',{}).get(event_id)
    if (not isinstance(event,dict) or npc_id not in event.get('participants',[]) or
            type(event.get('revision')) is not int or not 0<=event['revision']<=state['revision']):
        raise RuleError('人物新屬性必須由已確認事件觸發。')
    contracts=state.get('world',{}).get('social_contracts',{})
    options={key:rule['label'] for key,rule in contracts.items() if rule['npc_id']==npc_id}
    payload={'npc_id':npc_id,'event_text':event['text'],
             'existing_values':state['npcs'][npc_id]['social_state']['values'],
             'possible_interactions':options}
    instruction=('只根據已確認 event_text 提出一個尚未記錄的人物情緒、行為傾向或需要，'
                 'kind 只選 emotion/priority/trait/need/relation；ID 由程式分配，唔需要輸出。'
                 'initial_value 必須是 0–10，source_quote 必須逐字出自 event_text。'
                 'effects.contract_id 只可用 possible_interactions 的 ID，唔可以填人物數值 ID；'
                 '無肯定影響就填 []。direction 表示它支持或阻礙該請求。'
                 '不能把玩家單方面宣告當已發生事件。只回 JSON。')
    messages=[{'role':'system','content':instruction+'\n'+
               json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]
    measured=count(base_url,messages);limit=budget(base_url,400)
    if limit and measured is not None and measured>limit:
        raise RuleError('人物屬性提案超過模型容量，故事未執行。')
    schema=copy.deepcopy(SOCIAL_PROPOSAL_SCHEMA)
    schema['properties']['effects']['items']['properties']['contract_id']={
        'type':'string','enum':list(options)}
    raw=complete(messages,base_url,400,.15,response_schema=schema,raw=True)
    proposal=parse_proposal(raw) if isinstance(raw,str) else raw
    return proposal,measured


def trial_dynamic_turn(state,text,base_url,complete=None,roller=None):
    """Interpret an action, stage one bounded extension if needed, then roll."""
    original=require_text(text,'玩家輸入')
    intent,first=compile_action(state,original,base_url,complete)
    proposal=None;extra=[]
    if intent['mode']=='play' and len(intent['steps'])==1 and (
            intent['steps'][0]['action']=='custom' and not intent['steps'][0]['negated']):
        repair=None
        for attempt in range(2):
            proposal,tokens=propose_object_extension(
                state,original,intent['steps'][0]['target_id'],base_url,complete,repair)
            extra.append(tokens)
            try:register_object_extension(state,proposal)
            except RuleError as exc:
                if attempt:raise
                repair=(proposal,str(exc))
            else:break
    resolved_intent,decision=resolve_dynamic_intent(state,intent,proposal,roller)
    return {'intent':resolved_intent,'proposal':proposal,'decision':decision,
            'input_tokens':[first,*extra],'output_caps':[450,*([500]*len(extra))]}


def resolve_dynamic_intent(state,intent,proposal=None,roller=None):
    """Resolve a compiled intent and saved proposal without another model call."""
    intent=copy.deepcopy(intent)
    if intent['mode']!='play' or len(intent['steps'])!=1:
        raise RuleError('動態動作試驗只接受單一步驟。')
    step=intent['steps'][0];staged=state
    if step['action']=='custom' and not step['negated']:
        if proposal is None:raise RuleError('新動作缺少已保存的提案。')
        staged=register_object_extension(state,proposal)
        step['action']=next(iter(set(staged['world']['dynamic_actions'])-
                                 set(state.get('world',{}).get('dynamic_actions',{}))))
    elif proposal is not None:
        raise RuleError('既有動作不應附加新提案。')
    decision=resolve_values(staged,intent,roller)
    if staged is not state:
        patch=decision['changes'].setdefault('world',{})
        patch['attribute_definitions']=staged['world']['attribute_definitions']
        patch['dynamic_actions']=staged['world']['dynamic_actions']
        patch.setdefault('entities',{})[step['target_id']]=(
            decision['changes'].get('world',{}).get('entities',{}).get(step['target_id']) or
            staged['world']['entities'][step['target_id']])
    return intent,decision
