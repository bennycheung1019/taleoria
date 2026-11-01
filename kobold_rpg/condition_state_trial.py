"""Staging-only numeric condition and narration over a durable force decision."""
import copy
import hashlib
import json
import re

from .calibrated_difficulty_trial import (compile_calibrated_action,
    propose_force_profile,register_force_profile,resolve_profiled_force)
from .calibrated_gm_trial import host_force_narration,focused_dialogue
from .context_budget import budget,count
from .conversation_target import conversation_target,explicit_people,present_people
from .dynamic_pending_trial import _dice,_row,_save_once
from .engine import RuleError,require_text
from .gm_context import recent_context,recalled_object_context
from .model import _complete,parse_proposal
from .names import PAIR,chinese
from .social_values_trial import select_social_context,resolve_social,render_social
from .structured_state_trial import validate_values,resolve_values,render_host_narration


NARRATION_SCHEMA={'type':'object','properties':{
    'narration':{'type':'string'},
    'amendments':{'type':'array','maxItems':3,'items':{'type':'object','properties':{
        'field':{'type':'string','enum':['open','passable','lid_open','contents']},
        'value':{'anyOf':[{'type':'boolean'},{'type':'string'}]},
        'evidence':{'type':'string'}},
        'required':['field','value','evidence'],'additionalProperties':False}}},
                  'required':['narration'],'additionalProperties':False}
DAMAGE_BASE={'fragile':35,'light':30,'ordinary':25,'reinforced':20,
             'fortified':15,'extraordinary':10}


class UnsupportedSocialInteraction(RuleError):
    """A new-world NPC has no registered numeric social contract yet."""


class UnadjudicatedTrialAction(RuleError):
    """No outcome, roll, or world change exists; the RPG OS may handle it."""


def _addressed_person_pronoun(text):
    return bool(re.search(r'\bask\s+(?:him|her|them)\b',text,re.I) or
                re.search(r'問\s*(?:佢|他|她|嗰個人|那個人)',text))


def _addressed_solo_conversation(text):
    """A direct request for a person's explanation, even without punctuation."""
    return bool(re.search(r'\b(?:can|could|would)\s+you\s+(?:tell|explain|describe)\b|'
                          r'\btell\s+me\s+(?:more|about|what|why|how|where|who)\b|'
                          r'\b(?:what(?:\x27s| is)|tell me)\s+your\s+name\b',text,re.I)
                or re.search(r'你(?:可唔可以|可不可以|可以|能否|能不能).{0,8}(?:講|說|話我知|告訴我)|'
                             r'(?:講|話|告訴).{0,5}(?:我|本人).{0,6}(?:呢度|這裡|呢個地方)|'
                             r'你(?:叫咩名|叫什麼名字|叫甚麼名字|叫咩|叫什麼)',text))


def _mentions_npc_name(name,text):
    if name in text or chinese(name) in text:return True
    pair=PAIR.fullmatch(name.strip())
    return bool(pair and re.search(r'(?<![A-Za-z])'+re.escape(pair[2])+r'(?![A-Za-z])',
                                   text,re.I))


def _information_question(text):
    # A question spoken during an action is not a question-only turn. The
    # dialogue shortcut cannot adjudicate physical consequences.
    question=re.search(r'[？?]',text)
    if question:
        tail=text[question.end():]
        tail=re.sub(r'^[\s"”」\'’、，,。.!！;；:：]+','',tail)
        if tail:
            return False
    if (re.search(r'\b(?:and\s+then|and|then)\s+(?:i|we)\s+(?!ask\b|say\b|tell\b|speak\b|reply\b|answer\b)\w+',text,re.I)
            or '然後' in text or '跟住' in text):
        return False
    if _addressed_solo_conversation(text):
        return True
    if re.search(r'\b(?:i\s+)?(?:ask|asked)\b.{0,80}\b(?:why|what|who|where|when|how)\b',
                 text,re.I):
        return True
    if ('？' in text or '?' in text) and not re.search(
            r'請|可否|能否|願意|幫我|放我|給我',text):
        return True
    if re.search(r'\bask\s+(?:him|her|them)\s+to\b',text,re.I):
        return False
    if re.search(r'\bask\b.*\b(?:why|what|who|where|when|how|whether|if|about)\b',
                 text,re.I):
        return True
    return bool('問' in text and any(word in text for word in
                ('點解','為何','為甚麼','為什麼','點樣','如何','邊度','哪裡',
                 '乜','甚麼','什麼','幾時','誰','邊個')))


def _condition_sentence(entity):
    name=entity['name'];values=entity['values'];integrity=values['integrity']
    kind=entity.get('type');effect=entity['force_profile']['effect_key']
    if kind=='door':
        body=('表面完整' if integrity==100 else
              '門板完全毀壞' if integrity==0 else
              '門板有破口' if values.get(effect) is True else '門板受損')
        states=[]
        if values.get('open') is False:states.append('仍關著')
        elif values.get('open') is True:states.append('已打開')
        if values.get('locked') is True:states.append('仍上鎖')
        elif values.get('locked') is False:states.append('已解鎖')
        passage=('已可通過；門後情況未確定' if values.get('passable') is True
                 else '能否通過及門後情況未確定')
        suffix='；'.join((body,'、'.join(states) if states else '開關狀態未確定',
                        passage))
    else:
        body=('外表完整' if integrity==100 else
              '箱體結構完全毀壞' if integrity==0 else '箱體受損')
        lid=('箱蓋已打開' if values.get('lid_open') is True else '箱蓋位置未確定')
        contents=('箱內已確認空無一物' if values.get('contents')=='empty'
                  else '箱內情況未確定')
        suffix=body+'；'+lid+'；'+contents
    return f'{name}完整度 {integrity}/100；{suffix}。'


def _condition_unknowns(entity):
    values=entity['values']
    if entity.get('type')=='door':
        return (["能否通過"] if values.get('passable') is None else [])+['門後情況']
    return (["箱蓋位置"] if values.get('lid_open') is None else [])+(
        ['箱內情況'] if values.get('contents') is None else [])


def _asks_unknown_condition(entity,text):
    unknown=set(entity.get('condition_unknowns',[]))
    if entity.get('type')=='door':
        return (('門後情況' in unknown and any(term in text for term in
                 ('門後','後面','裡面','裏面'))) or
                ('能否通過' in unknown and any(term in text for term in
                 ('通過','穿過','走過','進去'))))
    return (('箱內情況' in unknown and any(term in text for term in
             ('箱內','箱裏','箱裡','裡面','裏面'))) or
            ('箱蓋位置' in unknown and '箱蓋' in text))


def apply_condition_result(state,decision):
    """Attach sourced numeric changes to the same entity change as the roll."""
    if decision.get('status')!='resolved' or len(decision.get('steps',[]))!=1:
        raise RuleError('完整度只適用於已裁定的單一動作。')
    step=decision['steps'][0]
    if step.get('action')!='force' or step.get('status') not in (
            'succeeded','failed','no_effect','not_attempted'):
        raise RuleError('完整度只適用於強行動作。')
    target=step.get('target_id') or (decision['rolls'][0]['target_id']
                                   if decision.get('rolls') else None)
    if target is None:
        # A negated action has no target in the old resolver and changes nothing.
        return copy.deepcopy(decision)
    prior=state.get('world',{}).get('entities',{}).get(target)
    if not isinstance(prior,dict):raise RuleError('完整度目標不存在。')
    updated=copy.deepcopy(decision)
    entities=updated['changes'].setdefault('world',{}).setdefault('entities',{})
    entity=copy.deepcopy(entities.get(target,prior))
    profile=entity.get('force_profile')
    if not isinstance(profile,dict):raise RuleError('完整度缺少已建立的物件強度。')
    if entity.get('type') not in ('door','crate'):
        raise RuleError('此物件類型未有可驗證的狀況描述規則。')
    if profile.get('effect_key') not in ('breached','broken') or profile.get('tier') not in DAMAGE_BASE:
        raise RuleError('位移或未知強度不能當成結構損傷。')
    current=prior['values'].get('integrity')
    if current is None:
        source=profile['initial_source_quote']
        if (prior['values'].get(profile['effect_key']) is True or
                not re.search(r'完整|無瑕|未有破損',source)):
            raise RuleError('初始完整度缺少明確的完整外觀來源。')
        current=100
        entity['value_sources']['integrity']={
            'revision':state['revision'],'source':source}
    if type(current) is not int or not 0<=current<=100:
        raise RuleError('已保存的物件完整度無效。')
    damage=0
    if step['status']=='succeeded':
        roll=updated['rolls'][0]
        damage=min(60,DAMAGE_BASE[profile['tier']]+
                   max(0,roll['total']-roll['target'])*2)
        damage=min(current,damage)
        entity['values']['integrity']=current-damage
        entity['value_sources']['integrity']={
            'revision':state['revision']+1,
            'source':'successful force roll; damage '+str(damage)}
    else:
        entity['values']['integrity']=current
    if updated['rolls']:
        updated['rolls'][0]['integrity_damage']=damage
    entity['condition_sentence']=_condition_sentence(entity)
    entity['condition_unknowns']=_condition_unknowns(entity)
    entity['condition_source_revision']=(state['revision']+
        (1 if step['status']=='succeeded' else 0))
    entities[target]=entity
    updated['changes']['world']['focus_object_id']=target
    updated['condition_delta']={'target_id':target,'before':current,
                                'after':entity['values']['integrity'],
                                'damage':damage}
    candidate=copy.deepcopy(state)
    candidate['world']['entities'][target]=entity
    validate_values(candidate)
    return updated


def prepare_condition_decision(engine,request_id,revision,text,base_url,complete=None):
    """Freeze intent, first-contact profile, die and condition in copied SQLite."""
    original=require_text(text,'玩家輸入')
    key='condition:'+require_text(request_id,'行動識別',200)
    row=_row(engine,key,original,revision)
    state=engine.state()
    if state['revision']!=revision:
        raise RuleError('故事在行動處理期間已更新。')
    if row['decision'] is not None:return json.loads(row['decision'])
    if row['intent'] is None:
        intent,_=compile_calibrated_action(state,original,base_url,complete)
        intent=_save_once(engine,key,'intent',intent)
    else:intent=json.loads(row['intent'])
    if intent['mode']!='play' or len(intent['steps'])!=1:
        raise RuleError('此試驗目前只接通單一步驟。')
    action=intent['steps'][0]['action']
    if action=='persuade':
        npc_id=intent['steps'][0]['target_id']
        npc=state['npcs'].get(npc_id)
        if (isinstance(npc,dict) and npc.get('known') and
                npc.get('location')==state['pc']['location'] and
                not isinstance(npc.get('social_state'),dict)):
            raise UnsupportedSocialInteraction('此人物尚未建立數值社交規則。')
        if npc_id is None and _addressed_person_pronoun(original):
            present=[person for person in state['npcs'].values() if
                     person.get('known') and person.get('location')==state['pc']['location']]
            if len(present)==1 and not isinstance(present[0].get('social_state'),dict):
                raise UnsupportedSocialInteraction('此人物尚未建立數值社交規則。')
        proposal=json.loads(row['proposal']) if row['proposal'] is not None else None
        if proposal is None:
            proposal,_=select_social_context(state,npc_id,original,base_url,complete)
            proposal=_save_once(engine,key,'proposal',proposal)
        social=resolve_social(state,npc_id,proposal,_dice(row['seed']))
        if social['status'] in ('succeeded','refused','blocked'):
            social['changes'].setdefault('world',{}).setdefault('social_outcomes',{})[
                'revision_'+str(state['revision']+1)]={
                    'npc_id':npc_id,'contract_id':social['contract_id'],
                    'status':social['status'],'revision':state['revision']+1,
                    'player_declaration':original[:240],
                    'source':'host_social_contract'}
        decision={'status':'resolved' if social['status'] in
                  ('succeeded','refused','blocked') else 'needs_judgment',
                  'steps':[{'action':'persuade','status':social['status'],
                            'target_id':npc_id}],
                  'changes':social['changes'],'rolls':social['rolls'],
                  'social_result':social}
        return _save_once(engine,key,'decision',{'intent':intent,
            'proposal':proposal,'decision':decision})
    if action in ('move','unlock','open','observe'):
        decision=resolve_values(state,intent,_dice(row['seed']))
        changed=decision.get('changes',{}).get('world',{}).get('entities',{})
        for changed_entity in changed.values():
            if (isinstance(changed_entity,dict) and
                    type(changed_entity.get('values',{}).get('integrity')) is int and
                    isinstance(changed_entity.get('force_profile'),dict)):
                changed_entity['condition_sentence']=_condition_sentence(changed_entity)
                changed_entity['condition_source_revision']=state['revision']+1
        return _save_once(engine,key,'decision',{'intent':intent,
            'proposal':None,'decision':decision})
    if action!='force':
        raise RuleError('此動作尚未有安全的裁定及敘述流程。')
    target=intent['steps'][0]['target_id']
    entity=state.get('world',{}).get('entities',{}).get(target)
    proposal=json.loads(row['proposal']) if row['proposal'] is not None else None
    if (not intent['steps'][0]['negated'] and isinstance(entity,dict) and
            entity.get('location')==state['pc']['location'] and
            'force_profile' not in entity and proposal is None):
        proposed,_=propose_force_profile(state,target,base_url,complete)
        register_force_profile(state,target,proposed['tier'],proposed['effect_key'],
                               proposed['initial'],proposed['source_quote'],
                               proposed['initial_source_quote'])
        proposal=_save_once(engine,key,'proposal',proposed)
    decision=resolve_profiled_force(state,intent,proposal,_dice(row['seed']),
                                    allow_repeat_damage=True)
    decision['steps'][0].setdefault('target_id',target)
    decision=apply_condition_result(state,decision)
    return _save_once(engine,key,'decision',{'intent':intent,
        'proposal':proposal,'decision':decision})


def _unsupported_narration(entity,prose,text,decision):
    values=entity['values'];kind=entity.get('type')
    if entity['name'] not in prose:
        return '敘述沒有指明裁定目標。'
    allowed_numbers={decision['condition_delta']['before'],
                     decision['condition_delta']['after']}
    if any(int(value) not in allowed_numbers for value in
           re.findall(r'(?<!\d)(\d{1,3})\s*/\s*100',prose)):
        return '敘述使用未裁定的完整度數值。'
    if kind=='door':
        if values.get('open') is False and re.search(
                r'門.{0,8}(?:已打開|打開了|敞開|半開)|'
                r'未完全(?:打開|開啟)|沒有完全(?:打開|開啟)',prose):
            return '門被寫成打開。'
        if values.get('passable') is not True and re.search(
                r'可容.{0,8}通過|可以通過|能夠通過|足以.{0,8}通過',prose):
            return '破口被寫成可通過。'
    if kind=='crate':
        if values.get('contents')!='empty' and re.search(
                r'空蕩蕩|空無一物|空空如也',prose):
            return '箱內被寫成已知。'
        if values.get('lid_open') is not True and re.search(
                r'箱蓋.{0,6}(?:打開|掀開|翻開)|木板向兩側翻開',prose):
            return '箱蓋被寫成已打開。'
    for tool in ('獵刀','撬棍','繩索','斧頭','大鎚'):
        if tool in prose and tool not in text:return '敘述加入未聲明的工具。'
    return None


def reconcile_narrative_amendments(state,decision,prose,amendments):
    """Accept only compatible, cited new facts in the same turn as the prose."""
    if not isinstance(amendments,list) or len(amendments)>3:
        raise RuleError('新事實提案格式無效。')
    candidate=copy.deepcopy(decision)
    target=candidate['condition_delta']['target_id']
    entity=candidate['changes']['world']['entities'][target]
    values=entity['values'];seen=set()
    if amendments and candidate['steps'][0]['status']!='succeeded':
        raise RuleError('失敗的行動不能新增成功後果。')
    for row in amendments:
        if (not isinstance(row,dict) or set(row)!={'field','value','evidence'} or
                not isinstance(row['field'],str) or row['field'] in seen or
                not isinstance(row['evidence'],str) or
                len(row['evidence'].strip())<4 or row['evidence'] not in prose):
            raise RuleError('新事實缺少敘述原文或欄位重複。')
        field=row['field'];value=row['value'];seen.add(field)
        if field=='open':
            valid=(entity.get('type')=='door' and value is True and
                   values.get('locked') is False and values['integrity']<=70 and
                   values.get('open') is False and
                   re.search(r'門.{0,8}(?:打開|開啟|敞開|半開)',row['evidence']))
        elif field=='passable':
            valid=(entity.get('type')=='door' and value is True and
                   values['integrity']<=30 and values.get('passable') is None and
                   re.search(r'可.{0,8}(?:通過|穿過)|足以.{0,8}通過',row['evidence']))
        elif field=='lid_open':
            valid=(entity.get('type')=='crate' and value is True and
                   values['integrity']<=60 and values.get('lid_open') is None and
                   re.search(r'箱蓋.{0,8}(?:打開|翻開|掀開)',row['evidence']))
        elif field=='contents':
            valid=(entity.get('type')=='crate' and value=='empty' and
                   values.get('lid_open') is True and values.get('contents') is None and
                   re.search(r'箱內.{0,8}(?:空|沒有|無)',row['evidence']))
        else:valid=False
        if not valid:raise RuleError('新事實與已裁定狀態或可見範圍衝突。')
        values[field]=value
        entity['value_sources'][field]={
            'revision':state['revision']+1,
            'source':'accepted GM narration: '+row['evidence']}
    entity['condition_sentence']=_condition_sentence(entity)
    entity['condition_unknowns']=_condition_unknowns(entity)
    staged=copy.deepcopy(state);staged['world']['entities'][target]=entity
    validate_values(staged)
    candidate['narrative_amendments']=copy.deepcopy(amendments)
    return candidate


def narrate_condition(state,text,decision,base_url,complete=None,
                      with_amendments=False):
    """AI writes prose; deterministic checks catch known high-impact claims."""
    complete=complete or _complete
    target=decision['condition_delta']['target_id']
    entity=decision['changes']['world']['entities'][target]
    roll=decision['rolls'][0] if decision['rolls'] else None
    payload={'player_declaration':text,'target':entity['name'],
             'established_source':entity['description'],
             'action_result':decision['steps'][0]['status'],
             'condition':{'integrity':entity['values']['integrity'],
                          'short_description':entity['condition_sentence'],
                          'other_values':{key:value for key,value in entity['values'].items()
                                          if key!='integrity'}},
             'unknowns':entity.get('condition_unknowns',[]),
             'roll':{'success':roll['success'],'damage':roll['integrity_damage']}
                    if roll else None}
    allowed_fields=(['open','passable'] if entity.get('type')=='door' else
                    ['lid_open','contents'])
    instruction=('你是 RPG 敘述者。程式裁定與狀態是權威，只寫玩家聲明的這次動作和物件直接結果。'
                 '用自然的繁體中文寫一至兩句；完整度是 0 至 100，數值越低損傷越重。'
                 '短狀況句是事實摘要，不要原句照抄。未知項目不能推論成已知；'
                 '破損不等於打開、可通行或看見內部。不要新增工具、人物、後續行動或玩家決定。'
                 '失敗不可寫成成功。若成功後確實出現額外物理後果，可用 amendments '
                 '提出此物件的 '+','.join(allowed_fields)+' 欄位；'
                 'open 只指門扇打開，lid_open 只指箱蓋打開；'
                 '並逐字引用 narration 內真正描述該欄位的證據；'
                 '沒有額外後果就用空陣列。程式會檢查前提，同一回合先接受新事實。只回 JSON。')
    messages=[{'role':'system','content':instruction+'\n'+
               json.dumps(payload,ensure_ascii=False,separators=(',',':'))},
              {'role':'user','content':text}]
    tokens=count(base_url,messages);limit=budget(base_url,350)
    if limit and tokens is not None and tokens>limit:
        raise RuleError('敘述提示超過模型容量。')
    schema=copy.deepcopy(NARRATION_SCHEMA)
    schema['properties']['amendments']['items']['properties']['field']['enum']=allowed_fields
    raw=complete(messages,base_url,350,.25,response_schema=schema,raw=True)
    data=parse_proposal(raw) if isinstance(raw,str) else raw
    prose=(data.get('narration') if isinstance(data,dict) and
           set(data) in ({'narration'},{'narration','amendments'}) else None)
    if not isinstance(prose,str) or not prose.strip() or len(prose)>700:
        raise RuleError('AI 敘述格式無效。')
    proposed=(data.get('amendments',[]) if with_amendments else [])
    revised=reconcile_narrative_amendments(state,decision,prose,proposed)
    entity=revised['changes']['world']['entities'][target]
    issue=_unsupported_narration(entity,prose,text,revised)
    if issue:raise RuleError(issue)
    return (prose,tokens,revised) if with_amendments else (prose,tokens)


def make_condition_gm(engine,complete=None,observations=None):
    """GM callable for an injected staging HTTP handler; never default startup."""
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
        if _information_question(original):
            here=state['pc']['location']
            present=list(present_people(state))
            people=explicit_people(state,original)
            if len(people)>1:raise RuleError('問題涉及多名人物，請講明目標。')
            if not people:
                target=conversation_target(state,original)
                if target:people=[target]
                elif len(present)>1 and (_addressed_person_pronoun(original) or
                                          _addressed_solo_conversation(original) or
                                          re.search(r'\bask(?:ed)?\b',original,re.I)):
                    raise RuleError('附近有多名人物，請講明你想問邊位；故事未執行。')
            local_object_mentioned=any(item.get('location')==here and
                item.get('name') and (item['name'] in original or
                chinese(item['name']) in original)
                for item in state.get('world',{}).get('entities',{}).values())
            focus_item=state.get('world',{}).get('entities',{}).get(
                state.get('world',{}).get('focus_object_id'))
            if (not local_object_mentioned and focus_item and
                    focus_item.get('location')==here and
                    any(word in original for word in ('佢','它','嗰個','那個'))):
                local_object_mentioned=True
            if len(people)==1 and not local_object_mentioned and any(
                    rule.get('npc_id')==people[0] for rule in
                    state.get('world',{}).get('social_contracts',{}).values()
                    if isinstance(rule,dict)):
                # A free dialogue must not bypass a registered knowledge gate.
                people=[]
            if len(people)==1:
                person=state['npcs'][people[0]]
                mentioned_remote=[item for item in state.get('world',{}).get('entities',{}).values()
                    if item.get('location')!=here and item.get('name') and
                    (item['name'] in original or chinese(item['name']) in original)]
                local_named=any(item.get('location')==here and item.get('name') and
                    (item['name'] in original or chinese(item['name']) in original)
                    for item in state.get('world',{}).get('entities',{}).values())
                if mentioned_remote and not local_named and not any(
                        any(chinese(item['name']) in str(fact) for item in mentioned_remote)
                        for fact in person.get('knowledge',[])):
                    from .npc_visibility import public_name
                    prose=f'{public_name(person)}說：「我唔清楚你講嗰件遠處物件嘅情況。」'
                    observations.append({'route':'knowledge_guard',
                                         'narration_source':'host','calls':calls})
                    return {'narration':prose,'changes':{'scene_focus':people},'bookkeeping':'ready'}
                local_objects=[item for item in state.get('world',{}).get('entities',{}).values()
                    if item.get('location')==here and item.get('name') and
                    (item['name'] in original or chinese(item['name']) in original)]
                if not local_objects and any(word in original for word in ('佢','它','嗰個','那個')):
                    focus=state.get('world',{}).get('focus_object_id')
                    item=state.get('world',{}).get('entities',{}).get(focus)
                    if item and item.get('location')==here:local_objects=[item]
                unknown_terms=('門後','後面','箱內','箱裏','箱裡','裡面','裏面')
                if len(local_objects)==1 and _asks_unknown_condition(local_objects[0],original):
                    item=local_objects[0]
                    known_facts=[*person.get('knowledge',[]),
                        *(fact.get('text','') for fact in
                          person.get('social_state',{}).get('knowledge',{}).values()
                          if isinstance(fact,dict) and fact.get('known') is True)]
                    if item.get('condition_unknowns') and not any(
                            any(term in str(fact) for term in unknown_terms)
                            for fact in known_facts):
                        factual=item.get('condition_sentence','')
                        from .npc_visibility import public_name
                        prose=f'{factual}{public_name(person)}說：「我唔清楚當中未知嘅情況。」'
                        observations.append({'route':'knowledge_guard',
                                             'narration_source':'host','calls':calls})
                        return {'narration':prose,'changes':{'scene_focus':people},'bookkeeping':'ready'}
                recent_rows,_=recent_context(engine,state)
                older=recalled_object_context(engine,state,original,
                    [row['revision'] for row in recent_rows])
                prose,_=focused_dialogue(state,original,people[0],recent_rows,
                                         base_url,measured,older_object_events=older)
                observations.append({'route':'focused_dialogue','narration_source':'ai',
                                     'older_object_events':len(older),'calls':calls})
                return {'narration':prose,'changes':{'scene_focus':people},'bookkeeping':'ready'}
        frozen=prepare_condition_decision(engine,request_hash,state['revision'],
                                          original,base_url,measured)
        decision=frozen['decision']
        if decision['status']!='resolved':
            if (decision.get('changes')=={} and not decision.get('rolls') and
                decision.get('steps') and all(step.get('status')=='unresolved'
                                              for step in decision['steps'])):
                raise UnadjudicatedTrialAction('試驗流程未能裁定這次行動。')
            raise RuleError('行動未有安全裁定。')
        if frozen['intent']['steps'][0]['action']=='persuade':
            prose=render_social(state,original,decision['social_result'])
            observations.append({'route':'social_contract','narration_source':'host',
                                 'status':decision['social_result']['status'],
                                 'calls':calls})
            return {'narration':prose,'changes':decision['changes'],
                    'bookkeeping':'ready'}
        if frozen['intent']['steps'][0]['action']!='force':
            prose=render_host_narration(state,decision)
            if not prose:raise RuleError('此動作尚未有安全敘述。')
            observations.append({'route':'structured_action','narration_source':'host',
                                 'action':frozen['intent']['steps'][0]['action'],
                                 'calls':calls})
            return {'narration':prose,'changes':decision['changes'],
                    'bookkeeping':'ready'}
        try:
            prose,_,decision=narrate_condition(state,original,decision,base_url,
                                                measured,with_amendments=True)
            source='ai'
        except (RuleError,ValueError,TypeError) as exc:
            prose=host_force_narration(state,decision)
            source='host_fallback';issue=str(exc)
        record={'route':'condition_force','narration_source':source,
                'condition_delta':decision.get('condition_delta'),
                'narrative_amendments':decision.get('narrative_amendments',[]),
                'calls':calls}
        if source=='host_fallback':record['narration_issue']=issue
        observations.append(record)
        return {'narration':prose,'changes':decision['changes'],
                'bookkeeping':'ready'}
    return gm
