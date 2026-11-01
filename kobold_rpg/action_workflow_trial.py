"""Unsaved AI intent compiler and event-bound narrator experiment.

This module never evaluates AI-authored code. State mutation is returned as a
candidate delta; the caller must commit after successful narration.
"""
import copy
import hashlib
import json
import re

from .action_registry_trial import PRIMITIVES, STEP_KEYS, RULE_KEYS, FLAGS, evidence_sources, resolve, rules, validate_intent, validate_difficulty
from .context_budget import budget, count
from .engine import RuleError, require_text
from .model import _complete, parse_proposal


def _nullable_string():
    return {'anyOf': [{'type': 'string'}, {'type': 'null'}]}


FACTOR_SCHEMA={'type':'object','properties':{
    'source_id':{'type':'string'},'quote':{'type':'string','maxLength':60},
    'impact':{'type':'integer','minimum':-6,'maximum':6},'reason':{'type':'string','maxLength':80}},
    'required':['source_id','quote','impact','reason'],'additionalProperties':False}
DIFFICULTY_SCHEMA={'type':'object','properties':{
    'base':{'type':'integer','enum':[10]},
    'factors':{'type':'array','maxItems':3,'items':FACTOR_SCHEMA},
    'target':{'type':'integer','minimum':2,'maximum':30}},
    'required':['base','factors','target'],'additionalProperties':False}
FOCUSED_DIFFICULTY_SCHEMA={'type':'object','properties':{
    'factors':{'type':'array','maxItems':3,'items':{'type':'object','properties':{
        'source_id':{'type':'string'},'impact':{'type':'integer','minimum':-6,'maximum':6},
        'reason':{'type':'string','maxLength':80}},
        'required':['source_id','impact','reason'],'additionalProperties':False}}},
    'required':['factors'],'additionalProperties':False}
STEP_SCHEMA={'type':'object','properties':{
    'primitive':{'type':'string','enum':sorted(PRIMITIVES)},
    **{key:_nullable_string() for key in STEP_KEYS-{'primitive','negated','difficulty'}},
    'difficulty':{'anyOf':[{'type':'null'},DIFFICULTY_SCHEMA]},
    'negated':{'type':'boolean'}},
    'required':sorted(STEP_KEYS),'additionalProperties':False}
RULE_SCHEMA={'type':'object','properties':{
    'id':{'type':'string'},'aliases':{'type':'array','items':{'type':'string'}},
    'scope':{'type':'string'},'operator':{'type':'string','enum':['set_entity_flag']},
    'required_capability':{'type':'string'},'required_item':{'type':'string'},
    'required_flag':{'type':'object','properties':{'name':{'type':'string'},'value':{'type':'boolean'}},
                     'required':['name','value'],'additionalProperties':False},
    'roll':{'type':'object','properties':{key:{'type':'integer'} for key in ('count','sides','modifier','target')},
            'required':['count','sides','modifier','target'],'additionalProperties':False},
    'effect':{'type':'object','properties':{'name':{'type':'string'},'value':{'type':'boolean'}},
              'required':['name','value'],'additionalProperties':False},
    'basis':{'type':'string'}},'required':sorted(RULE_KEYS),'additionalProperties':False}
INTENT_SCHEMA={'type':'object','properties':{
    'mode':{'type':'string','enum':['play','ooc']},
    'steps':{'type':'array','maxItems':4,'items':STEP_SCHEMA},
    'new_rule':{'anyOf':[{'type':'null'},RULE_SCHEMA]}},
    'required':['mode','steps','new_rule'],'additionalProperties':False}
STORY_SCHEMA={'type':'object','properties':{
    'decision_id':{'type':'string'},'narration':{'type':'string'}},
    'required':['decision_id','narration'],'additionalProperties':False}
AUDIT_SCHEMA={'type':'object','properties':{
    'consistent':{'type':'boolean'},
    'conflicts':{'type':'array','items':{'type':'string'}},
    'added_pc_actions':{'type':'array','items':{'type':'string'}},
    'unsupported_facts':{'type':'array','items':{'type':'string'}}},
    'required':['consistent','conflicts','added_pc_actions','unsupported_facts'],
    'additionalProperties':False}


def _context(state, text):
    here=state['pc']['location']
    world=state.get('world',{})
    entries=rules(state)
    matching=[entry for entry in entries if any(alias.casefold() in text.casefold() for alias in entry['aliases'])]
    nearby={key:{'name':npc['name'],'role':npc.get('role',''),'location':npc['location']}
            for key,npc in state['npcs'].items() if npc['location']==here}
    return {'world_id':state['campaign_id'],'revision':state['revision'],
            'contract':{key:state['contract'].get(key) for key in ('genre','difficulty','randomness','play_form')},
            'pc':{'id':state['pc']['id'],'name':state['pc']['name'],
                  'location':here,'capabilities':state['pc']['capabilities'],
                  'spells':state['pc']['spells'],'inventory':state['pc']['inventory']},
            'place':{here:state['locations'][here]},
            'nearby_people':nearby,
            'entities_here':{key:value for key,value in world.get('entities',{}).items()
                             if value.get('location')==here},
            'matching_action_rules':matching,
            'difficulty_evidence':evidence_sources(state)}


def _parsed(raw):
    return parse_proposal(raw) if isinstance(raw,str) else raw


def compile_intent(state, text, base_url, complete=None):
    """AI maps wording to generic operations or proposes a scoped rule."""
    complete=complete or _complete
    original=require_text(text,'玩家輸入')
    scene=_context(state,original)
    instruction=('你只把最後一則玩家原句編譯成動作意圖 JSON，不決定成功或失敗，不敘事。'
                 '分清 OOC、真正說出口的台詞、內心想法、否定和順序。'
                 '先把新講法／複合動作映射到通用原語 observe, speak, move, use_ability, custom, judgment；'
                 'judgment 表示沒有可計算的通用規則，不能假裝已成功。'
                 'use_ability 只指回合前已登記的超自然法術或力量；普通技巧和工具（例如開鎖）用 custom 或 judgment。'
                 '只有世界已有目標物件，而且玩家回合前已有能力或工具，並需要「擲骰後修改物件布林狀態」的新程序時，'
                 '才提議 new_rule；否則填 null。新規則只能限本 world_id，operator=set_entity_flag，'
                 '不可創造能力、物品或事實，不可從玩家宣告推定成功。'
                 '新規則 id 暫填 new_action，由程式分配正式 ID；對應 step 亦用 rule_id=new_action。'
                 '每個實際使用 custom 規則的步驟都要由你按本次具體情況評估 difficulty：base 固定10，'
                 'factors 逐項引用 difficulty_evidence 的 source_id 和原文 quote，impact 為 -6 至 +6，'
                 'target=10+所有 impact。只能引用本回合前已建立的證據；無額外因素用空陣列及 target10。'
                 'base10 已假設規則必需的技能及工具可用，不可因具備 required_capability 或 required_item 再降低難度。'
                 '難度在擲骰前決定，不能看擲骰結果後改。非 custom 步驟 difficulty=null。'
                 'required_flag/effect 的 name 必須是物件已有的布林旗標（例如 locked），effect.value 是改變後值，'
                 '不能寫動作名字。step 的 target_id 用已存在 ID；未知保留 null。negated 真表示玩家明確不做。'
                 '台詞逐字放 utterance，未說出的想法不要當台詞。只回 JSON。')
    messages=[{'role':'system','content':instruction+'\n已建立資料：\n'+
               json.dumps(scene,ensure_ascii=False,separators=(',',':'))},
              {'role':'user','content':original}]
    input_tokens=count(base_url,messages)
    limit=budget(base_url,850)
    if limit and input_tokens is not None and input_tokens>limit:
        raise RuleError('動作編譯超過本機模型容量，故事未執行。')
    schema=copy.deepcopy(INTENT_SCHEMA)
    rule_fields=schema['properties']['new_rule']['anyOf'][1]['properties']
    rule_fields['id']={'type':'string','enum':['new_action']}
    rule_fields['scope']={'type':'string','enum':[state['campaign_id']]}
    rule_fields['required_flag']['properties']['name']={'type':'string','enum':sorted(FLAGS)}
    rule_fields['effect']['properties']['name']={'type':'string','enum':sorted(FLAGS)}
    schema['properties']['steps']['items']['properties']['difficulty']['anyOf'][1]['properties']['factors']['items']['properties']['source_id']={
        'type':'string','enum':list(scene['difficulty_evidence'])}
    raw=complete(messages,base_url,850,.2,response_schema=schema,raw=True)
    intent=validate_intent(_parsed(raw))
    existing={entry['id'] for entry in rules(state)}
    for step in intent['steps']:
        if (not step['negated'] and step['rule_id'] in existing and
                step['target_id'] in state.get('world',{}).get('entities',{})):
            step['primitive']='custom'
    if intent['new_rule'] is not None:
        provisional=intent['new_rule']['id']
        assigned=f'action_{state["revision"]+1}_{len(rules(state))+1}'
        intent['new_rule']['id']=assigned
        for step in intent['steps']:
            if step['rule_id']==provisional:
                step['rule_id']=assigned
        # Reconcile a tool action that the model mislabeled as a supernatural
        # ability. The item and target must both exist before the turn; this
        # never supplies a new power or accepts an unsupported effect.
        candidates=[step for step in intent['steps'] if step['target_id'] in
                    state.get('world',{}).get('entities',{}) and
                    step['item_id']==intent['new_rule']['required_item'] and
                    step['item_id'] in state['pc']['inventory'] and
                    step['primitive']=='use_ability' and step['rule_id'] is None]
        if len(candidates)==1:
            candidates[0]['primitive']='custom'
            candidates[0]['rule_id']=assigned
        related=[step for step in intent['steps'] if step['primitive']=='custom' and
                 step['rule_id']==assigned and step['target_id'] in state.get('world',{}).get('entities',{})]
        if len(related)==1:
            entity=state['world']['entities'][related[0]['target_id']]
            effect=intent['new_rule']['effect']
            current=entity.get('flags',{}).get(effect['name'])
            if (type(current) is bool and current is not effect['value'] and
                    intent['new_rule']['required_flag']['name']==effect['name']):
                intent['new_rule']['required_flag']['value']=current
        # A proposed rule for speech or an explicitly unattempted thought has
        # no action to govern. Discard it rather than adding a game mechanic.
        if not related:
            intent['new_rule']=None
            for step in intent['steps']:
                if step['rule_id']==assigned:
                    step['rule_id']=None
    return intent,input_tokens


def assign_missing_difficulties(state,text,intent,base_url,complete=None):
    """Use a focused extra AI call only when a calculable step lacks valid DC."""
    complete=complete or _complete
    catalog={entry['id']:entry for entry in rules(state)}
    if intent['new_rule'] is not None:catalog[intent['new_rule']['id']]=intent['new_rule']
    token_counts=[]
    for step in intent['steps']:
        if step['negated'] or step['primitive']!='custom' or step['rule_id'] not in catalog:
            continue
        rule=catalog[step['rule_id']]
        if step['difficulty'] is not None:
            try:
                validate_difficulty(state,step['difficulty'],rule)
                continue
            except RuleError:
                pass
        sources={key:value for key,value in evidence_sources(state).items() if len(value)<=60}
        request={'action':text,'target_id':step['target_id'],
                 'rule':rule,'world_evidence':sources}
        instruction=('只評估本次動作的擲骰難度，不決定成敗，不敘事。'
                     '從 world_evidence 選最多三項真正改變難度的 source_id，對每項給 -6 至 +6 impact 及簡短 reason。'
                     '不要輸出原文 quote、base 或 target；程式會從 source_id 取得原文並計算 target。'
                     'base10 已包括規則 required_capability 及 required_item，不能把必需技能／工具重複算作減難度。'
                     '不應因玩家想成功而調低，亦不得假設未記錄的鎖具材料、天氣效果或人物技能。'
                     '如果沒有可證的額外因素，用 factors=[]。只回 JSON。')
        messages=[{'role':'system','content':instruction+'\n'+json.dumps(request,ensure_ascii=False,separators=(',',':'))},
                  {'role':'user','content':text}]
        measured=count(base_url,messages);limit=budget(base_url,600)
        if limit and measured is not None and measured>limit:
            raise RuleError('難度評估超過本機模型容量，故事未執行。')
        schema=copy.deepcopy(FOCUSED_DIFFICULTY_SCHEMA)
        schema['properties']['factors']['items']['properties']['source_id']={
            'type':'string','enum':list(sources)}
        candidate=_parsed(complete(messages,base_url,600,.15,response_schema=schema,raw=True))
        if (not isinstance(candidate,dict) or set(candidate)!={'factors'} or
                not isinstance(candidate['factors'],list) or len(candidate['factors'])>3):
            raise RuleError('難度評估格式不完整，故事未執行。')
        factors=[]
        for factor in candidate['factors']:
            if (not isinstance(factor,dict) or set(factor)!={'source_id','impact','reason'} or
                    factor['source_id'] not in sources):
                raise RuleError('難度評估引用了不存在的證據。')
            factors.append({**factor,'quote':sources[factor['source_id']]})
        proposed={'base':10,'factors':factors,
                  'target':10+sum(factor['impact'] for factor in factors)}
        step['difficulty']=validate_difficulty(state,proposed,rule)
        token_counts.append(measured)
    return intent,token_counts


def narrate(state,text,decision,base_url,complete=None):
    """AI renders the host decision; result is not committed here."""
    complete=complete or _complete
    original=require_text(text,'玩家輸入')
    digest=hashlib.sha256(json.dumps(decision,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]
    scene=_context(state,original)
    destination=decision.get('changes',{}).get('pc',{}).get('location',state['pc']['location'])
    payload={'decision_id':digest,'original':original,'scene':scene,
             'host_result':decision,
             'resolved_place':{destination:state['locations'][destination]}}
    instruction=('依 host_result 寫一至三段繁體中文自然回覆。host_result 的成功／失敗、擲骰、'
                 '位置及資源變化是唯一權威；不得改寫或重新擲骰。'
                 'unresolved／needs_judgment 不是成功，對方同意或物理結果不能自動補定。'
                 '不代玩家加台詞、心情、承諾或下一步行動。不要新增能力或改變已建立事實。'
                 '若是 OOC，直接回答問題，不當遊戲行動。'
                 '回傳 decision_id 原值及 narration；不要列內部資料。')
    messages=[{'role':'system','content':instruction+'\n'+
               json.dumps(payload,ensure_ascii=False,separators=(',',':'))},
              {'role':'user','content':original}]
    input_tokens=count(base_url,messages)
    limit=budget(base_url,1100)
    if limit and input_tokens is not None and input_tokens>limit:
        raise RuleError('敘事超過本機模型容量，故事未執行。')
    raw=complete(messages,base_url,1100,.45,response_schema=STORY_SCHEMA,raw=True)
    story=_parsed(raw)
    if not isinstance(story,dict) or story.get('decision_id')!=digest or not isinstance(story.get('narration'),str) or not story['narration'].strip():
        raise RuleError('敘事沒有確認已裁定的結果，故事未執行。')
    return story['narration'],input_tokens


def audit_narration(state,text,decision,narration,base_url,complete=None):
    """Independent semantic check before any story/save is committed."""
    # A second pass by the same model missed this exact contradiction in a
    # real local sample. Keep a narrow, explicit check for this observed failure.
    # This does not solve arbitrary prose entailment.
    entities=decision.get('changes',{}).get('world',{}).get('entities',{})
    for entity in entities.values():
        if ((entity.get('values',entity.get('flags',{}))).get('open') is False and '門' in entity.get('name','') and
                re.search(r'門縫.{0,6}(?:微啟|敞開|打開|開啟)|門.{0,4}(?:已打開|已開啟|打開了|敞開了)',
                          narration)):
            raise RuleError('敘事寫出門已打開，但裁定只記錄門仍關著；故事未執行。')
    complete=complete or _complete
    payload={'player_action':text,'before':_context(state,text),
             'host_result':decision,'candidate_narration':narration}
    instruction=('獨立核對候選敘事，不改寫故事。只有 host_result 明確裁定的世界變化才可當成已發生。'
                 '例如 locked=false、open=false 代表解鎖但門仍關著；「門縫微啟」也暗示門已打開。'
                 '檢查所有多加的玩家行動／台詞、未經證實的新事實、失敗寫成成功、NPC 未知的秘密。'
                 '如任何列表非空，consistent=false。回傳 JSON。')
    messages=[{'role':'system','content':instruction+'\n'+
               json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]
    input_tokens=count(base_url,messages)
    limit=budget(base_url,350)
    if limit and input_tokens is not None and input_tokens>limit:
        raise RuleError('敘事核對超過本機模型容量，故事未執行。')
    finding=_parsed(complete(messages,base_url,350,0,response_schema=AUDIT_SCHEMA,raw=True))
    if (not isinstance(finding,dict) or set(finding)!=set(AUDIT_SCHEMA['required']) or
            type(finding['consistent']) is not bool or
            any(not isinstance(finding[key],list) or any(not isinstance(item,str) for item in finding[key])
                for key in ('conflicts','added_pc_actions','unsupported_facts'))):
        raise RuleError('敘事核對格式無效，故事未執行。')
    if not finding['consistent'] or any(finding[key] for key in ('conflicts','added_pc_actions','unsupported_facts')):
        raise RuleError('敘事與已裁定結果或玩家原意不一致，故事未執行：'+
                        '；'.join((finding['conflicts']+finding['added_pc_actions']+
                                  finding['unsupported_facts'])[:3]))
    return finding,input_tokens


def trial_turn(state,text,base_url,complete=None,roller=None):
    """Return an audited candidate without writing state or a save."""
    intent,first_tokens=compile_intent(state,text,base_url,complete)
    intent,extra_tokens=assign_missing_difficulties(state,text,intent,base_url,complete)
    decision=resolve(state,intent,roller)
    narration,second_tokens=narrate(state,text,decision,base_url,complete)
    audit,audit_tokens=audit_narration(state,text,decision,narration,base_url,complete)
    return {'intent':intent,'decision':decision,'narration':narration,
            'audit':audit,'input_tokens':[first_tokens,*extra_tokens,second_tokens,audit_tokens],
            'output_caps':[850,*([600]*len(extra_tokens)),1100,350]}
