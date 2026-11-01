"""Staging-only adapter for one complete calibrated /api/play turn.

Construct with an Engine for a disposable save. It is deliberately not wired
into the default server startup or live Taleoria configuration.
"""
import hashlib
import json
import re

from .calibrated_pending_trial import prepare_calibrated_decision
from .context_budget import budget,count
from .engine import RuleError,require_text
from .gm import reply as legacy_reply
from .model import _complete,parse_proposal


DIALOGUE_SCHEMA={'type':'object','properties':{'narration':{'type':'string'}},
                 'required':['narration'],'additionalProperties':False}


def focused_dialogue(state,text,npc_id,recent,base_url,complete,
                     older_object_events=None):
    """One bounded model call for a question to a present, known NPC."""
    npc=state.get('npcs',{}).get(npc_id)
    if not isinstance(npc,dict) or npc.get('location')!=state['pc']['location'] or not npc.get('known'):
        raise RuleError('目前沒有可交談的已知人物。')
    here=state['pc']['location']
    recent_rows=(recent or [])[-2:]
    entities=state.get('world',{}).get('entities',{})
    explicit={key for key,item in entities.items() if item.get('location')==here and
              (key in text or (item.get('name') and item['name'] in text))}
    resolved_reference=None
    if not explicit:
        # Pronouns can refer to the object in the latest established turn.
        for row in reversed(recent_rows):
            mentioned=[key for key,item in entities.items() if item.get('location')==here and
                       (key in row.get('declaration','') or
                        (item.get('name') and item['name'] in
                         (row.get('declaration','')+' '+row.get('narration',''))))]
            if len(mentioned)>1 and re.search(r'佢|它|嗰個|那個',text):
                raise RuleError('代詞可能指向多件物件，請講明目標；故事未執行。')
            if len(mentioned)==1:
                explicit={mentioned[0]}
                if re.search(r'佢|它|嗰個|那個',text):
                    key=mentioned[0]
                    resolved_reference={'target_id':key,'name':entities[key]['name'],
                                        'source_revision':row['revision']}
                break
    if not explicit and re.search(r'佢|它|嗰個|那個',text):
        key=state.get('world',{}).get('focus_object_id')
        if key in entities and entities[key].get('location')==here:
            explicit={key}
            resolved_reference={'target_id':key,'name':entities[key]['name'],
                                'source_revision':entities[key].get('condition_source_revision',0)}
    objects={key:{'name':item.get('name'),'description':item.get('description',''),
                  'values':item.get('values',{})}
             for key,item in entities.items() if key in explicit}
    current_facts=[]
    for item in objects.values():
        values=item['values'];name=item['name']
        if item.get('values',{}).get('breached') is True:
            current_facts.append(f'{name}目前已有破口。')
        elif item.get('values',{}).get('breached') is False:
            current_facts.append(f'{name}目前未有破口。')
        if values.get('open') is False:current_facts.append(f'{name}目前仍然關著。')
        if values.get('locked') is True:current_facts.append(f'{name}目前仍然上鎖。')
    history=[{'revision':row['revision'],'player':row['declaration'],
              'narration':row['narration'],'npc_present':npc_id in row.get('witnesses',[])}
             for row in recent_rows]
    interpreted_question=re.sub(r'\bask\s+(?:him|her|them)\b',
                                lambda match:re.sub(r'\b(?:him|her|them)\b',npc['name'],
                                                    match.group(),flags=re.I),
                                text,count=1,flags=re.I)
    context={'place':state['locations'][here],
             'npc':{key:npc.get(key) for key in
                    ('name','public_name','name_known','description','anchor','encounter','knowledge','conditions')},
             'focused_objects':objects,'current_established_facts':current_facts,
             'recent_complete_exchanges':history,
             'older_sourced_object_events':(older_object_events or [])[-2:],
             'player_question':text,'resolved_reference':resolved_reference,
             'interpreted_question':(re.sub(r'佢|它|嗰個|那個',resolved_reference['name'],
                                            interpreted_question,count=1)
                                     if resolved_reference else interpreted_question)}
    instruction=('你只回覆這次玩家對在場人物的問題，寫一至兩段自然繁體中文對話與可觀察反應。'
                 '人物只知道自己的紀錄、親身可感知的已發生事件，或玩家現在說出口的內容；'
                 'npc_present 不代表知道門後秘密。沿用最近完整對話的先後；'
                 'older_sourced_object_events 是世界狀態歷史，people_present_not_proven_knowers'
                 ' 只表示同場，絕不證明此 NPC 曾看見或知道該事件。'
                 'current_established_facts 是最新權威，上一回合已改變的物件不能回到更早狀態。'
                 '如有 resolved_reference，玩家代詞只指該物件；按 interpreted_question 的意思答覆，'
                 '不要改成問主角或其他人。'
                 '不可代玩家說話、行動或決定；不可改門、位置、物品、能力或 NPC 承諾。'
                 'name_known:false 時，name 是內部資料；先用 public_name 或外貌稱呼。若玩家問姓名，可自然回答「我叫...」，之後玩家才知道名字。'
                 '不知道就直接說不知道，唔好補故事事實；不要重複前一次 NPC 答覆。'
                 '只回 JSON narration，不要技術 ID。')
    messages=[{'role':'system','content':instruction+'\n'+
               json.dumps(context,ensure_ascii=False,separators=(',',':'))},
              {'role':'user','content':text}]
    tokens=count(base_url,messages);limit=budget(base_url,550)
    if limit and tokens is not None and tokens>limit:
        raise RuleError('人物對話超過本機模型容量，故事未執行。')
    raw=complete(messages,base_url,550,.35,response_schema=DIALOGUE_SCHEMA,raw=True)
    data=parse_proposal(raw) if isinstance(raw,str) else raw
    prose=data.get('narration') if isinstance(data,dict) and set(data)=={'narration'} else None
    if not isinstance(prose,str) or not prose.strip() or len(prose)>1200:
        raise RuleError('人物對話格式不完整，故事未執行。')
    # Known mechanical contradiction; broader narrative truth is evaluated
    # separately and remains a product limitation.
    for item in objects.values():
        values=item['values']
        if values.get('open') is False and re.search(r'門.{0,4}(?:已打開|已開啟|打開了|敞開了)',prose):
            raise RuleError('人物對話誤寫門已打開。')
    return prose,tokens


def host_force_narration(state,decision):
    step=decision['steps'][0];target=step.get('target_id')
    entity=state.get('world',{}).get('entities',{}).get(target,{})
    name=entity.get('name','目標')
    effect=(entity.get('force_profile') or
            decision.get('changes',{}).get('world',{}).get('entities',{}).get(target,{}).get('force_profile') or
            {}).get('effect_key')
    change={'breached':'出現破口','broken':'受損','moved':'移位'}.get(effect)
    if change is None:raise RuleError('缺少可敘述的物件結果。')
    status=step['status']
    if status=='succeeded':main=f'你嘗試對{name}施力，這次令它{change}。'
    elif status=='failed':main=f'你嘗試對{name}施力，這次未能令它{change}。'
    elif status=='no_effect':main=f'你對{name}的這次嘗試沒有造成新變化。'
    elif status=='not_attempted':main=f'你沒有嘗試破壞{name}。'
    else:raise RuleError('未有可敘述的強行動作裁定。')
    saved=decision.get('changes',{}).get('world',{}).get('entities',{}).get(target,entity)
    values=saved.get('values',{})
    if saved.get('type')=='door':
        if values.get('open') is False:main+='門仍然關著。'
        if values.get('locked') is True:main+='門鎖仍然鎖著。'
    return main


def make_calibrated_gm(engine,legacy_gm=legacy_reply,complete=None,observations=None):
    """Return a GM callable for make_handler(..., gm=...) on an isolated copy."""
    complete=complete or _complete
    observations=observations if observations is not None else []
    def gm(state,text,base_url,recent=None,state_provenance=None):
        original=require_text(text,'玩家輸入')
        request_hash=hashlib.sha256((state['campaign_id']+'\n'+
            str(state['revision'])+'\n'+original).encode()).hexdigest()
        calls=[]
        def measured(messages,url,maximum,temperature,**kwargs):
            calls.append({'input_tokens':count(url,messages),'output_cap':maximum})
            return complete(messages,url,maximum,temperature,**kwargs)
        frozen=prepare_calibrated_decision(engine,request_hash,state['revision'],
                                           original,base_url,measured)
        intent=frozen['intent'];decision=frozen['decision']
        step=intent['steps'][0]
        record={'revision':state['revision'],'action':step['action'],'calls':calls}
        if step['action']!='force':
            if (step['action'] in ('unlock','open','move') or
                    step['action'] in state.get('world',{}).get('dynamic_actions',{}) or
                    step['action'] in decision.get('changes',{}).get('world',{}).get('dynamic_actions',{})):
                record['route']='unsupported_mechanic';observations.append(record)
                raise RuleError('此已裁定機械動作尚未接通安全敘述，故事未執行。')
            npc_id=step.get('target_id')
            if (step['action'] in ('speak','custom','unknown') and npc_id in state.get('npcs',{})
                    and '？' in original):
                try:
                    prose,_=focused_dialogue(state,original,npc_id,recent,
                                              base_url,measured)
                except (RuleError,ValueError) as exc:
                    record['dialogue_issue']=str(exc)
                else:
                    record['route']='focused_dialogue';observations.append(record)
                    return {'narration':prose,'changes':{},'bookkeeping':'ready'}
            record['route']='legacy';observations.append(record)
            return legacy_gm(state,original,base_url,recent=recent,
                             state_provenance=state_provenance)
        if decision['status']!='resolved':
            record['route']='unresolved';observations.append(record)
            raise RuleError('這次行動缺少可驗證的物件狀態，故事未執行。')
        # Model narration was observed inventing an unmentioned knife and an
        # opened crate lid; a second model audit accepted it. For this trial,
        # only the deterministic host sentence may describe physical effects.
        prose=host_force_narration(state,decision)
        record['route']='calibrated';record['narration_source']='host'
        observations.append(record)
        return {'narration':prose,'changes':decision['changes'],
                'bookkeeping':'ready'}
    return gm
