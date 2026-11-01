"""Isolated experiment: AI interprets an action; host reads typed world values.

Only a deliberately small set of mechanics is implemented. Unsupported
actions remain unresolved rather than receiving invented numeric outcomes.
"""
import copy
import json
import re

from .context_budget import budget, count
from .engine import RuleError, require_text
from .model import _complete, parse_proposal
from .action_workflow_trial import narrate, audit_narration


ACTIONS={'observe','speak','move','unlock','open','persuade','custom','unknown'}
STEP_SCHEMA={'type':'object','properties':{
    'action':{'type':'string','enum':sorted(ACTIONS)},
    'target_id':{'anyOf':[{'type':'string'},{'type':'null'}]},
    'item_id':{'anyOf':[{'type':'string'},{'type':'null'}]},
    'utterance':{'anyOf':[{'type':'string'},{'type':'null'}]},
    'negated':{'type':'boolean'},
    'requires_previous_success':{'type':'boolean'}},
    'required':['action','target_id','item_id','utterance','negated','requires_previous_success'],
    'additionalProperties':False}
INTENT_SCHEMA={'type':'object','properties':{
    'mode':{'type':'string','enum':['play','ooc']},
    'steps':{'type':'array','maxItems':4,'items':STEP_SCHEMA}},
    'required':['mode','steps'],'additionalProperties':False}


def register_door(state,entity_id,name,location,source,*,locked=None,open=None,
                  jammed=None,lock_dc=None):
    """Stage a newly encountered door; unspecified values stay unknown."""
    if (not isinstance(entity_id,str) or not re.fullmatch(r'[a-z][a-z0-9_]{2,63}',entity_id) or
            not isinstance(name,str) or not name.strip() or
            location not in state['locations'] or not isinstance(source,str) or not source.strip() or
            entity_id in state.get('world',{}).get('entities',{})):
        raise RuleError('新物件的 ID、位置或來源無效。')
    values={'locked':locked,'open':open,'jammed':jammed,'lock_dc':lock_dc}
    result=copy.deepcopy(state)
    result.setdefault('world',{}).setdefault('entities',{})[entity_id]={
        'name':name,'type':'door','location':location,'values':values,
        'value_sources':{key:{'revision':state['revision'],'source':source}
                         for key,value in values.items() if value is not None}}
    validate_values(result)
    return result


def validate_values(state):
    """Unknown fields are omitted/None; unknown is never treated as false."""
    world=state.get('world',{})
    if not isinstance(world,dict):raise RuleError('世界數值資料格式錯誤。')
    for key,entity in world.get('entities',{}).items():
        if not isinstance(entity,dict) or not isinstance(entity.get('values'),dict):
            raise RuleError('物件缺少結構化狀態。')
        values=entity['values']
        if entity.get('type')=='door':
            for flag in ('locked','open','jammed'):
                if values.get(flag) is not None and type(values[flag]) is not bool:
                    raise RuleError('門的狀態只能是真、假或未知。')
            dc=values.get('lock_dc')
            if dc is not None and (type(dc) is not int or not 2<=dc<=25):
                raise RuleError('門鎖難度超出範圍。')
            if values.get('locked') is True and values.get('open') is True:
                raise RuleError('同一道門不能同時上鎖並敞開。')
        sources=entity.get('value_sources',{})
        if not isinstance(sources,dict) or any(
                name not in values or not isinstance(record,dict) or
                type(record.get('revision')) is not int or
                not isinstance(record.get('source'),str) or not record['source']
                for name,record in sources.items()):
            raise RuleError('物件數值缺少有效來源。')
        if any(value is not None and name not in sources for name,value in values.items()):
            raise RuleError('已建立物件數值必須有來源。')
    for place,values in world.get('environment',{}).items():
        if place not in state['locations'] or not isinstance(values,dict):
            raise RuleError('環境數值位置錯誤。')
        records=world.get('environment_sources',{}).get(place,{})
        if not isinstance(records,dict) or any(
                value is not None and (not isinstance(records.get(name),dict) or
                type(records[name].get('revision')) is not int or
                not isinstance(records[name].get('source'),str) or not records[name]['source'])
                for name,value in values.items()):
            raise RuleError('環境數值缺少有效來源。')
        for field,minimum,maximum in (('heat_c',-50,70),('visibility',0,100),('danger',0,10)):
            value=values.get(field)
            if value is not None and (type(value) is not int or not minimum<=value<=maximum):
                raise RuleError('環境數值超出範圍。')
    for npc in state['npcs'].values():
        values=npc.get('metrics',{})
        if not isinstance(values,dict) or any(type(v) is not int or not 0<=v<=10
                    for v in values.values()):
            raise RuleError('人物量表超出範圍。')
        records=npc.get('metric_sources',{})
        if not isinstance(records,dict) or any(
                not isinstance(records.get(name),dict) or
                type(records[name].get('revision')) is not int or
                not isinstance(records[name].get('source'),str) or not records[name]['source']
                for name in values):
            raise RuleError('人物數值缺少有效來源。')
    definitions=world.get('attribute_definitions',{})
    if not isinstance(definitions,dict):raise RuleError('動態屬性定義格式錯誤。')
    for identifier,definition in definitions.items():
        if (not isinstance(identifier,str) or '.' not in identifier or
                not isinstance(definition,dict) or
                definition.get('kind') not in ('int','bool')):
            raise RuleError('動態屬性定義無效。')
        target_type,key=identifier.split('.',1)
        for entity in world.get('entities',{}).values():
            if entity.get('type')!=target_type or key not in entity['values']:continue
            value=entity['values'][key]
            if value is None:continue
            if definition['kind']=='bool' and type(value) is not bool:
                raise RuleError('動態布林狀態格式錯誤。')
            if definition['kind']=='int' and (type(value) is not int or
                    type(definition.get('min')) is not int or
                    type(definition.get('max')) is not int or
                    not definition['min']<=value<=definition['max']):
                raise RuleError('動態數值超出已登記範圍。')
    return state


def relevant_context(state):
    validate_values(state)
    here=state['pc']['location'];world=state.get('world',{})
    return {'revision':state['revision'],
            'pc':{'location':here,'capabilities':state['pc']['capabilities'],
                  'inventory':state['pc']['inventory']},
            'place':{'id':here,'name':state['locations'][here]['name']},
            'environment':world.get('environment',{}).get(here,{}),
            'objects':{key:{'name':value['name'],'type':value.get('type'),
                             'values':value['values']}
                       for key,value in world.get('entities',{}).items()
                       if value.get('location')==here},
            'people':{key:{'name':npc['name'],'metrics':npc.get('metrics',{})}
                      for key,npc in state['npcs'].items() if npc['location']==here},
            'available_actions':{key:{'label':rule.get('label',''),
                                      'target_type':rule.get('target_type')}
                                 for key,rule in world.get('dynamic_actions',{}).items()},
            'recent_words':state.get('recent_dialogue',[])[-2:]}


def compile_action(state,text,base_url,complete=None):
    complete=complete or _complete
    original=require_text(text,'玩家輸入')
    scene=relevant_context(state)
    instruction=('只把玩家原句轉成意圖 JSON，不決定難度、成功、NPC 同意或敘事。'
                 '只用已列 ID；按原句順序拆步。玩家否定的動作用 negated=true。'
                 '內心想法不是台詞或實際行動；說出口的話放 utterance。'
                 '「成功先...」等條件在後一步設 requires_previous_success=true；其餘 false。'
                 'unlock 是嘗試解除鎖定，open 是實際推開已解鎖的門，兩者不可混淆。'
                 '玩家請求 NPC 做事用 persuade，但不能預設 NPC 同意。'
                 '未登記的物理動作用 custom，已登記的新動作用相應 action_id。'
                 '其他沒有通用動作用 unknown。OOC 用 mode=ooc、steps=[]。只回 JSON。')
    messages=[{'role':'system','content':instruction+'\n場景數值：'+
               json.dumps(scene,ensure_ascii=False,separators=(',',':'))},
              {'role':'user','content':original}]
    tokens=count(base_url,messages);limit=budget(base_url,450)
    if limit and tokens is not None and tokens>limit:
        raise RuleError('意圖編譯超過模型容量，故事未執行。')
    allowed=ACTIONS|set(state.get('world',{}).get('dynamic_actions',{}))
    schema=copy.deepcopy(INTENT_SCHEMA)
    schema['properties']['steps']['items']['properties']['action']['enum']=sorted(allowed)
    raw=complete(messages,base_url,450,.15,response_schema=schema,raw=True)
    intent=parse_proposal(raw) if isinstance(raw,str) else raw
    if (not isinstance(intent,dict) or set(intent)!={'mode','steps'} or
            intent['mode'] not in ('play','ooc') or not isinstance(intent['steps'],list) or
            len(intent['steps'])>4 or (intent['mode']=='ooc')!= (not intent['steps'])):
        raise RuleError('行動意圖格式不正確，故事未執行。')
    for step in intent['steps']:
        if (not isinstance(step,dict) or set(step)!=set(STEP_SCHEMA['required']) or
                step['action'] not in allowed or type(step['negated']) is not bool or
                type(step['requires_previous_success']) is not bool or
                any(step[key] is not None and not isinstance(step[key],str)
                    for key in ('target_id','item_id','utterance'))):
            raise RuleError('行動步驟格式不正確，故事未執行。')
    return intent,tokens


def resolve_values(state,intent,roller=None):
    """Return candidate changes; never mutate source state or invent unknowns."""
    import secrets
    validate_values(state)
    roller=roller or (lambda sides:secrets.randbelow(sides)+1)
    candidate=copy.deepcopy(state);outcomes=[];rolls=[];changed_entities={}
    if intent['mode']=='ooc':
        return {'status':'ooc','steps':[],'changes':{},'rolls':[]}
    for step in intent['steps']:
        action=step['action'];target=step['target_id'];here=candidate['pc']['location']
        if step['negated']:
            outcomes.append({'action':action,'status':'not_attempted'});continue
        if step['requires_previous_success'] and (not outcomes or outcomes[-1]['status']!='succeeded'):
            outcomes.append({'action':action,'status':'not_attempted',
                             'reason':'前一步未成功，條件動作不執行'});continue
        entity=candidate.get('world',{}).get('entities',{}).get(target)
        if action=='observe':
            npc=candidate['npcs'].get(target)
            if (isinstance(entity,dict) and entity.get('location')==here or
                    isinstance(npc,dict) and npc.get('location')==here and npc.get('known') or
                    target==here):
                outcomes.append({'action':action,'status':'perception','target_id':target})
            else:
                outcomes.append({'action':action,'status':'unresolved',
                                 'reason':'目標不在目前可觀察的場景'})
        elif action=='speak':
            outcomes.append({'action':action,'status':'spoken','utterance':step['utterance'] or ''})
        elif action=='move':
            route=candidate['locations'][here]['exits'].get(target)
            if route and route.get('known') is True and route.get('clear') is True:
                candidate['pc']['location']=target
                outcomes.append({'action':action,'status':'succeeded','destination':target})
            else:outcomes.append({'action':action,'status':'unresolved','reason':'沒有已知可通行路線'})
        elif action in ('unlock','open'):
            if not isinstance(entity,dict) or entity.get('type')!='door' or entity.get('location')!=here:
                outcomes.append({'action':action,'status':'unresolved','reason':'目前地點沒有這道已建立的門'});continue
            values=entity['values']
            if action=='open':
                if values.get('locked') is False and values.get('open') is False and values.get('jammed') is False:
                    values['open']=True
                    entity['value_sources']['open']={'revision':state['revision']+1,'source':'player action:open'}
                    changed_entities[target]=copy.deepcopy(entity)
                    outcomes.append({'action':action,'status':'succeeded','target_id':target})
                else:outcomes.append({'action':action,'status':'unresolved','reason':'門未確認可打開，可能上鎖、卡住或狀態未知'})
                continue
            if values.get('locked') is not True or values.get('lock_dc') is None:
                outcomes.append({'action':action,'status':'unresolved','reason':'鎖定狀態或鎖難度未知'});continue
            if ('開鎖' not in state['pc']['capabilities'] or
                    state['pc']['inventory'].get('lockpick',0)<1 or step['item_id']!='lockpick'):
                outcomes.append({'action':action,'status':'no_effect','reason':'沒有已建立的開鎖能力與工具'});continue
            env=candidate.get('world',{}).get('environment',{}).get(here,{})
            factors=[]
            if env.get('visibility') is not None and env['visibility']<40:
                factors.append({'source':'environment.visibility','value':env['visibility'],'impact':2})
            if env.get('heat_c') is not None and env['heat_c']>=40:
                factors.append({'source':'environment.heat_c','value':env['heat_c'],'impact':2})
            dc=values['lock_dc']+sum(row['impact'] for row in factors)
            die=roller(20)
            if type(die) is not int or not 1<=die<=20:raise RuleError('骰子數值無效。')
            total=die+2;success=total>=dc
            rolls.append({'action':'unlock','target_id':target,'die':die,'skill_bonus':2,
                          'base_dc':values['lock_dc'],'factors':factors,'target':dc,
                          'total':total,'success':success})
            if success:
                values['locked']=False
                entity['value_sources']['locked']={'revision':state['revision']+1,'source':'successful unlock roll'}
                changed_entities[target]=copy.deepcopy(entity)
            outcomes.append({'action':action,'status':'succeeded' if success else 'failed','target_id':target})
        elif action=='persuade':
            npc=candidate['npcs'].get(target)
            outcomes.append({'action':action,'status':'unresolved',
                             'reason':'人物數值不能單獨證明請求可信、符合動機或取得同意',
                             'target_id':target if npc and npc['location']==here else None})
        elif action in candidate.get('world',{}).get('dynamic_actions',{}):
            rule=candidate['world']['dynamic_actions'][action]
            if (not isinstance(rule,dict) or
                    rule.get('operator')!='check_and_set_boolean' or
                    not isinstance(rule.get('target_type'),str) or
                    not isinstance(rule.get('difficulty_attribute'),str) or
                    not isinstance(rule.get('effect_attribute'),str) or
                    type(rule.get('effect_value')) is not bool):
                raise RuleError('已保存的新動作規則格式無效。')
            if (not isinstance(entity,dict) or entity.get('location')!=here or
                    entity.get('type')!=rule['target_type']):
                outcomes.append({'action':action,'status':'unresolved',
                                 'reason':'新動作沒有目前地點的適用目標'});continue
            values=entity['values'];difficulty=values.get(rule['difficulty_attribute'])
            before=values.get(rule['effect_attribute'])
            if (type(difficulty) is not int or not 2<=difficulty<=30 or
                    type(before) is not bool or
                    before is rule['effect_value']):
                outcomes.append({'action':action,'status':'unresolved',
                                 'reason':'新動作缺少已建立難度或目標狀態'});continue
            die=roller(20)
            if type(die) is not int or not 1<=die<=20:raise RuleError('骰子數值無效。')
            success=die>=difficulty
            rolls.append({'action':action,'target_id':target,'die':die,
                          'target':difficulty,'success':success})
            if success:
                values[rule['effect_attribute']]=rule['effect_value']
                entity['value_sources'][rule['effect_attribute']]={
                    'revision':state['revision']+1,'source':'successful action:'+action}
                changed_entities[target]=copy.deepcopy(entity)
            outcomes.append({'action':action,'status':'succeeded' if success else 'failed',
                             'target_id':target})
        else:outcomes.append({'action':action,'status':'unresolved','reason':'此行動尚無程式裁定規則'})
    changes={}
    if candidate['pc']['location']!=state['pc']['location']:
        changes['pc']={'location':candidate['pc']['location']}
    if changed_entities:changes['world']={'entities':changed_entities}
    status='resolved' if all(row['status'] not in ('unresolved','spoken') for row in outcomes) else 'needs_judgment'
    return {'status':status,'steps':outcomes,'changes':changes,'rolls':rolls}


def render_host_narration(state,decision):
    """Mechanical outcome text from frozen states; no model may add effects."""
    if decision['status']=='ooc':return None
    if any(row['action'] not in {'observe','move','unlock','open'} for row in decision['steps']):
        return None
    parts=[];entities=state.get('world',{}).get('entities',{})
    for row in decision['steps']:
        kind=row['action'];status=row['status'];target=row.get('target_id')
        name=(entities.get(target,{}).get('name') or
              state['npcs'].get(target,{}).get('name') or
              state['locations'].get(target,{}).get('name') or target or '目標')
        if status=='not_attempted':continue
        if kind=='observe':
            visible=(entities.get(target,{}).get('description') or
                     state['npcs'].get(target,{}).get('description') or
                     state['locations'].get(target,{}).get('description'))
            parts.append(f'你查看{name}。'+(visible if isinstance(visible,str) else ''))
        elif kind=='move':
            if status=='succeeded':
                dest=row['destination']
                parts.append(f'你沿已知通路走到{state["locations"][dest]["name"]}。')
            else:parts.append('你沒有找到已確認可通行的路線，位置未變。')
        elif kind=='unlock':
            if status=='succeeded':parts.append(f'你用已備的工具試開{name}；鎖已解開。')
            elif status=='failed':parts.append(f'你試開{name}的鎖，但這次沒有解開。')
            elif status=='no_effect':parts.append(f'你尚無已建立的工具或能力去開{name}的鎖。')
            else:parts.append(f'{name}的鎖定狀態或難度未確定，這次未能裁定開鎖結果。')
        elif kind=='open':
            if status=='succeeded':parts.append(f'你推開{name}；門現已打開。')
            else:parts.append(f'{name}尚未確認可以打開；門的狀態沒有改變。')
    changes=decision.get('changes',{}).get('world',{}).get('entities',{})
    for row in decision['steps']:
        if row['action']=='unlock' and row['status']=='succeeded':
            entity=changes.get(row['target_id'])
            if entity and entity['values']['open'] is False:
                parts.append(f'{entity["name"]}仍關著。')
    return ''.join(parts) or '你沒有執行被否定的動作。'


def trial_turn(state,text,base_url,complete=None,roller=None):
    intent,first=compile_action(state,text,base_url,complete)
    decision=resolve_values(state,intent,roller)
    host_text=render_host_narration(state,decision)
    if host_text is not None:
        return {'intent':intent,'decision':decision,'narration':host_text,
                'narration_source':'host','audit':{'consistent':True,'source':'deterministic'},
                'input_tokens':[first],'output_caps':[450]}
    narration,second=narrate(state,text,decision,base_url,complete)
    audit,third=audit_narration(state,text,decision,narration,base_url,complete)
    return {'intent':intent,'decision':decision,'narration':narration,'audit':audit,
            'narration_source':'model','input_tokens':[first,second,third],
            'output_caps':[450,1100,350]}
