"""Isolated trial: fixed physical difficulty from sourced scene properties.

The model identifies intent. A host rubric determines DC and applies only a
declared Boolean effect. Full story text remains in the durable world state.
"""
import copy
import json
import secrets
import re

from .context_budget import budget,count
from .dynamic_values_trial import (object_evidence,propose_object_extension,
                                   register_object_extension,resolve_dynamic_intent)
from .engine import RuleError,require_text
from .model import _complete,parse_proposal
from .structured_state_trial import ACTIONS,INTENT_SCHEMA,STEP_SCHEMA,resolve_values,validate_values


MAX_SCENE_OBJECTS=20
TIERS={'fragile':5,'light':10,'ordinary':15,'reinforced':20,
       'fortified':25,'extraordinary':30}
EFFECTS={'breached','broken','moved'}
TOOL_BONUS={'crowbar':2,'axe':2,'sledgehammer':3}
ITEM_ALIASES={'crowbar':('撬棍','鐵撬'),'axe':('斧頭','斧'),
              'sledgehammer':('大鎚','鐵鎚'),'rope':('繩','繩子'),
              'lockpick':('開鎖工具','撬鎖工具')}
FORCE_CAPABILITY='強力撞擊'
PROFILE_SCHEMA={'type':'object','properties':{
    'tier':{'type':'string','enum':list(TIERS)},
    'effect_key':{'type':'string','enum':sorted(EFFECTS)},
    'initial':{'type':'boolean'},
    'source_quote':{'type':'string'},
    'initial_source_quote':{'type':'string'}},
    'required':['tier','effect_key','initial','source_quote','initial_source_quote'],
    'additionalProperties':False}


def propose_force_profile(state,target_id,base_url,complete=None):
    """Optional scene-creation classifier; production should batch with scene setup."""
    complete=complete or _complete
    entity=state.get('world',{}).get('entities',{}).get(target_id)
    evidence=object_evidence(state,target_id)
    payload={'id':target_id,'type':entity['type'],'evidence':evidence}
    rubric=('按已有描述為一件物件分類「徒手強行破壞」基礎強度，唔計角色或工具。'
            '只選固定級別：fragile=5（紙／薄玻璃）、light=10（薄木箱）、'
            'ordinary=15（普通木門）、reinforced=20（厚木加鐵箍）、'
            'fortified=25（鐵門／石牆）、extraordinary=30（超常結構）。'
            '門被破壞結果只用 breached；其他物件可用 broken 或 moved。'
            'initial 必須根據現時完整／已損壞狀態，未有破口即 false。'
            '兩個 quote 分別支持強度與初始狀態，必須逐字取自 evidence。'
            '證據不足唔好猜；只回 JSON。')
    messages=[{'role':'system','content':rubric+'\n'+
               json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]
    tokens=count(base_url,messages);limit=budget(base_url,160)
    if limit and tokens is not None and tokens>limit:
        raise RuleError('場景物件分類超過模型容量。')
    raw=complete(messages,base_url,160,.15,response_schema=PROFILE_SCHEMA,raw=True)
    return (parse_proposal(raw) if isinstance(raw,str) else raw),tokens


def register_force_profile(state,target_id,tier,effect_key,initial,source_quote,
                           initial_source_quote):
    """Stage one reusable profile during scene creation or first encounter."""
    validate_values(state)
    entity=state.get('world',{}).get('entities',{}).get(target_id)
    if (not isinstance(entity,dict) or entity.get('location')!=state['pc']['location'] or
            tier not in TIERS or effect_key not in EFFECTS or type(initial) is not bool or
            not isinstance(source_quote,str) or len(source_quote.strip())<4 or
            not isinstance(initial_source_quote,str) or len(initial_source_quote.strip())<4 or
            (entity.get('type')=='door' and effect_key!='breached') or
            effect_key in entity.get('values',{}) or 'force_profile' in entity):
        raise RuleError('物件強度資料或目標無效。')
    evidence=object_evidence(state,target_id)
    if not all(any(quote in value for value in evidence.values())
               for quote in (source_quote,initial_source_quote)):
        raise RuleError('物件強度缺少已建立敘事來源。')
    current=[key for key,item in state['world']['entities'].items()
             if item.get('location')==state['pc']['location'] and 'force_profile' in item]
    if len(current)>=MAX_SCENE_OBJECTS:
        raise RuleError('此場景已達預先結構化物件上限；可稍後按焦點建立。')
    result=copy.deepcopy(state);entity=result['world']['entities'][target_id]
    entity['force_profile']={'tier':tier,'effect_key':effect_key,
                             'source_quote':source_quote,
                             'initial_source_quote':initial_source_quote,
                             'source_revision':state['revision']}
    entity['values'][effect_key]=initial
    entity['value_sources'][effect_key]={'revision':state['revision'],
                                         'source':initial_source_quote}
    validate_values(result)
    return result


def scene_context(state,text):
    """Only IDs/names required to interpret intent; never flatten story data."""
    validate_values(state)
    here=state['pc']['location'];world=state.get('world',{})
    objects={key:item for key,item in world.get('entities',{}).items()
             if item.get('location')==here}
    named=[key for key,item in objects.items()
           if key in text or (item.get('name') and item['name'] in text)]
    if len(named)>1:
        # Prefer the most specific name where a shorter name is its prefix.
        named=[key for key in named if not any(
            other!=key and objects[other].get('name','').startswith(objects[key].get('name',''))
            and len(objects[other].get('name',''))>len(objects[key].get('name',''))
            for other in named)]
    if named:
        if len(named)>MAX_SCENE_OBJECTS:raise RuleError('本句涉及太多物件。')
        objects={key:objects[key] for key in named}
    elif len(objects)>MAX_SCENE_OBJECTS:
        focus=world.get('focus_object_id')
        if focus not in objects:
            raise RuleError('場景物件過多而目標未能唯一辨認；故事未執行。')
        objects={focus:objects[focus]}
    inventory=[]
    for key,value in state['pc']['inventory'].items():
        if type(value) is not int or value<1:continue
        names=[key,*ITEM_ALIASES.get(key,())]
        catalog=state.get('item_catalog',{}).get(key,{})
        if isinstance(catalog,dict) and isinstance(catalog.get('name'),str):
            names.append(catalog['name'])
        if any(name in text for name in names):inventory.append(key)
    return {'revision':state['revision'],'place':here,
            'exits':{key:state['locations'][key]['name']
                     for key,route in state['locations'][here]['exits'].items()
                     if route.get('known') is True and key in state['locations']},
            'objects':{key:{'name':item['name'],'type':item.get('type')}
                       for key,item in objects.items()},
            'people':{key:npc['name'] for key,npc in state['npcs'].items()
                      if npc['location']==here},
            'inventory_names':inventory,
            'recent_words':state.get('recent_dialogue',[])[-2:]}


def compile_calibrated_action(state,text,base_url,complete=None):
    complete=complete or _complete
    original=require_text(text,'玩家輸入')
    context=scene_context(state,original)
    instruction=('只辨認玩家原句的意圖與目標，不估難度或成敗。'
                 '撞破、敲破、砸碎、劈破、撬破已建立物件用 force；解除鎖用 unlock；'
                 '推開已解鎖的門用 open，兩者不同。'
                 '移動至場景已列目的地用 move。'
                 '玩家要求 NPC 做事用 persuade，不預設同意。'
                 '只在玩家原句明確提到工具時填其 item_id；否則填 null，'
                 '不得擅自使用背包物品。'
                 '未涵蓋的物理動作用 custom，其他未知用 unknown。'
                 '玩家否定的動作設 negated=true；有「成功先」先設後步依賴。'
                 '說出口的話放 utterance，內心想法不是已發生行動。'
                 '玩家喺故事入面宣告行動或台詞時，必須 mode=play 並填 steps；'
                 '只有詢問遊戲外規則或設定先用 mode=ooc、steps=[]。'
                 'mode=ooc 時絕不可同時輸出行動步驟。只用已列 ID；只回 JSON。')
    messages=[{'role':'system','content':instruction+'\n場景：'+
               json.dumps(context,ensure_ascii=False,separators=(',',':'))},
              {'role':'user','content':original}]
    tokens=count(base_url,messages);limit=budget(base_url,450)
    if limit and tokens is not None and tokens>limit:
        raise RuleError('意圖編譯超過模型容量，故事未執行。')
    allowed=ACTIONS|{'force'}|set(state.get('world',{}).get('dynamic_actions',{}))
    schema=copy.deepcopy(INTENT_SCHEMA)
    schema['properties']['steps']['items']['properties']['action']['enum']=sorted(allowed)
    raw=complete(messages,base_url,450,.15,response_schema=schema,raw=True)
    intent=parse_proposal(raw) if isinstance(raw,str) else raw
    if (not isinstance(intent,dict) or set(intent)!={'mode','steps'} or
            intent['mode'] not in ('play','ooc') or not isinstance(intent['steps'],list) or
            len(intent['steps'])>4 or (intent['mode']=='ooc')!=(not intent['steps'])):
        raise RuleError('行動意圖格式不正確，故事未執行。')
    for step in intent['steps']:
        if (not isinstance(step,dict) or set(step)!=set(STEP_SCHEMA['required']) or
                step['action'] not in allowed or type(step['negated']) is not bool or
                type(step['requires_previous_success']) is not bool or
                any(step[key] is not None and not isinstance(step[key],str)
                    for key in ('target_id','item_id','utterance'))):
            raise RuleError('行動步驟格式不正確，故事未執行。')
        if step['action']=='force' and step['item_id'] not in context['inventory_names']:
            step['item_id']=None
        # The local model sometimes calls an ordinary break attempt `custom`.
        # Only this explicit, narrow verb family is safely the same primitive.
        target=state.get('world',{}).get('entities',{}).get(step['target_id'])
        if (intent['mode']=='play' and step['action']=='custom' and not step['negated']
                and isinstance(target,dict) and
                target.get('location')==state['pc']['location'] and
                re.search(r'撞破|敲破|砸碎|劈破|撬破|打碎|break|smash',
                          original,re.IGNORECASE)):
            step['action']='force'
            if step['item_id'] not in context['inventory_names']:
                step['item_id']=None
    return intent,tokens


def resolve_force(state,intent,roller=None,allow_repeat_damage=False):
    """Resolve one force step with a stable DC; unknown profiles never roll."""
    validate_values(state)
    if intent.get('mode')!='play' or len(intent.get('steps',[]))!=1:
        raise RuleError('強行動作試驗只接受單一步驟。')
    step=intent['steps'][0]
    if step['action']!='force':raise RuleError('不是強行動作。')
    target=step['target_id'];item=step['item_id'];here=state['pc']['location']
    if step['negated']:
        return {'status':'resolved','steps':[{'action':'force','status':'not_attempted'}],
                'changes':{},'rolls':[]}
    entity=state.get('world',{}).get('entities',{}).get(target)
    profile=entity.get('force_profile') if isinstance(entity,dict) else None
    if not isinstance(entity,dict) or entity.get('location')!=here or not isinstance(profile,dict):
        return {'status':'needs_judgment','steps':[{'action':'force','status':'unresolved',
                'reason':'目標未有已建立的強度資料'}],'changes':{},'rolls':[]}
    tier=profile.get('tier');effect=profile.get('effect_key')
    if (tier not in TIERS or effect not in EFFECTS or
            type(entity['values'].get(effect)) is not bool):
        raise RuleError('已保存的物件強度資料無效。')
    if entity['values'][effect] is True and (not allow_repeat_damage or
            entity['values'].get('integrity')==0):
        return {'status':'resolved','steps':[{'action':'force','status':'no_effect',
                'reason':'目標已處於該結果狀態'}],'changes':{},'rolls':[]}
    if item is not None and (item not in TOOL_BONUS or
            state['pc']['inventory'].get(item,0)<1):
        return {'status':'resolved','steps':[{'action':'force','status':'no_effect',
                'reason':'所用工具未在背包或沒有已建立效果'}],'changes':{},'rolls':[]}
    bonus=2 if FORCE_CAPABILITY in state['pc']['capabilities'] else 0
    tool_bonus=TOOL_BONUS.get(item,0)
    env=state['world'].get('environment',{}).get(here,{})
    # Only explicitly recorded physical hindrance applies to this primitive.
    penalty=env.get('force_penalty',0)
    sources=state['world'].get('environment_sources',{}).get(here,{})
    if (type(penalty) is not int or not 0<=penalty<=4 or
            (penalty>0 and 'force_penalty' not in sources)):
        raise RuleError('環境阻力缺少有效來源。')
    dc=TIERS[tier]+penalty
    die=(roller or (lambda sides:secrets.randbelow(sides)+1))(20)
    if type(die) is not int or not 1<=die<=20:raise RuleError('骰子數值無效。')
    total=die+bonus+tool_bonus;success=total>=dc
    roll={'action':'force','target_id':target,'die':die,'base_dc':TIERS[tier],
          'environment_penalty':penalty,'capability_bonus':bonus,
          'tool_bonus':tool_bonus,'target':dc,'total':total,'success':success}
    changes={}
    if success:
        changed=copy.deepcopy(entity);changed['values'][effect]=True
        changed['value_sources'][effect]={'revision':state['revision']+1,
                                          'source':'successful force roll'}
        changes={'world':{'entities':{target:changed}}}
    return {'status':'resolved','steps':[{'action':'force','status':
            'succeeded' if success else 'failed','target_id':target}],
            'changes':changes,'rolls':[roll]}


def resolve_profiled_force(state,intent,profile_proposal=None,roller=None,
                          allow_repeat_damage=False):
    """Preserve a newly learned profile even when this roll fails."""
    step=intent['steps'][0];target=step['target_id']
    staged=state
    if profile_proposal is not None:
        staged=register_force_profile(state,target,profile_proposal['tier'],
            profile_proposal['effect_key'],profile_proposal['initial'],
            profile_proposal['source_quote'],profile_proposal['initial_source_quote'])
    decision=resolve_force(staged,intent,roller,
                           allow_repeat_damage=allow_repeat_damage)
    if staged is not state:
        entities=decision['changes'].setdefault('world',{}).setdefault('entities',{})
        entities.setdefault(target,staged['world']['entities'][target])
    return decision


def trial_calibrated_turn(state,text,base_url,complete=None,roller=None):
    """Trial dispatch: fixed force or existing data-only action fallback."""
    original=require_text(text,'玩家輸入')
    intent,first=compile_calibrated_action(state,original,base_url,complete)
    if intent['mode']!='play' or len(intent['steps'])!=1:
        raise RuleError('校準難度試驗只接受單一步驟。')
    step=intent['steps'][0];extra=[];proposal=None;profile_proposal=None
    if step['action']=='force':
        target=step['target_id'];entity=state.get('world',{}).get('entities',{}).get(target)
        if (not step['negated'] and isinstance(entity,dict) and
                entity.get('location')==state['pc']['location'] and
                'force_profile' not in entity):
            profile_proposal,tokens=propose_force_profile(state,target,base_url,complete)
            extra.append((tokens,160))
        decision=resolve_profiled_force(state,intent,profile_proposal,roller)
    elif step['action']=='custom' and not step['negated']:
        repair=None
        for attempt in range(2):
            proposal,tokens=propose_object_extension(
                state,original,step['target_id'],base_url,complete,repair)
            extra.append((tokens,500))
            try:register_object_extension(state,proposal)
            except RuleError as exc:
                if attempt:raise
                repair=(proposal,str(exc))
            else:break
        intent,decision=resolve_dynamic_intent(state,intent,proposal,roller)
    else:decision=resolve_values(state,intent,roller)
    return {'intent':intent,'proposal':proposal,'profile_proposal':profile_proposal,
            'decision':decision,'input_tokens':[first,*[tokens for tokens,_ in extra]],
            'output_caps':[450,*[cap for _,cap in extra]]}
