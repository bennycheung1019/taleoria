"""RPG OS GM owns play. The host stores replies and structurally usable data.

No input classifier, keyword adjudication, or general narrative veto is used.
Player supernatural effects have the user's narrowly authorized source check.
Malformed bookkeeping never rejects a delivered story.
"""
import copy
import json
import re
import unicodedata
from .engine import RuleError, require_text
from .rulebook import verified_sources, section
from .story_text import story_text


def rules_packet():
    sources=verified_sources();law=sources['OS_LAW.md']
    agent_paragraphs=sources['OS_AGENT_STATE.md'].split('\n\n')
    capability_basis=next(p for p in agent_paragraphs if p.startswith('Before dependent behavior, including the first individually relevant encounter'))
    control_basis=next(p for p in agent_paragraphs if p.startswith('Locate the actual decision owner and any local discretion.'))
    # Retrieve the operative Freeform paragraphs, not character-build/session
    # administration text on every turn. All original sources stay unchanged.
    starts=('Use only when the operator selects it','Resolve uncertain outcomes by GM judgment',
            'Resolve one fitting response','The agreement governs initiative',"Under LAW's world delegation")
    freeform='\n\n'.join(p for p in sources['ENGINE_freeform.md'].split('\n\n') if p.startswith(starts))
    selected=[('OS/LAW.md — Prime directive',section(law,'## Prime directive — every PLAY response',1400)),
              ('OS/LAW.md — Understand',section(law,'## Understand',1400)),
              ('OS/LAW.md — Establish',section(law,'## Establish',2000)),
              ('OS/LAW.md — Resolve',section(law,'## Resolve',1900)),
              ('OS/LAW.md — Portray',section(law,'## Portray',1800)),
              ('ENGINE/freeform.md — operative paragraphs',freeform),
              ('OS/AGENT_STATE.md — Nature and control: capability basis',capability_basis),
              ('OS/AGENT_STATE.md — Nature and control: control transition',control_basis),
              ('OS/AGENT_STATE.md — Initial Encounter Baseline',section(sources['OS_AGENT_STATE.md'],'## Initial Encounter Baseline',900)),
              ('OS/AGENT_STATE.md — Personal anchors',section(sources['OS_AGENT_STATE.md'],'## Personal anchors and decisions (v1.01)',1100))]
    return '\n\n'.join('SOURCE: '+name+'\n'+body for name,body in selected)


SYSTEM='''依前述 RPG OS v1.01 原文執行 Understand → Establish → Resolve → Portray。你主持與裁定，程式只核對玩家超自然能力的既定來源；沒有普通行動或敘事批准者。
只用繁體中文自然敘事，名稱用中文（English Name）。保留玩家原意、粵語、短句、否定及連續行動；分清真正說出口的台詞、內在意圖與 OOC。不替玩家新增台詞、感受、承諾或下一個選擇。宣告是嘗試，不保證成功。
單一 system 內的 current_snapshot 是目前資料；其後 user/assistant 是依序發生的歷史，history_index 列版本、地點及 witnesses，只有當時在場者感知。最後一則 user 才是本次輸入，直接回答，不重演舊動作、問句或段落。NPC 不自動知道玩家背景、內心及其他人的秘密。
state_provenance 標示欄位實際更新版本，較舊不代表自動失效。初始景物、評價或等待狀態與較新經歷衝突時，依已接受的因果接續整理。bookkeeping incomplete/partial 的故事已發生，只補必要資料，不重做行動。
本網站保存原文與狀態，不要求玩家手動登記或操作檔案才肯回應。narration 給完整自然故事，一至三個短段落；不寫內部清單、檢查理由、技術錯誤或玩家下一步選項。
先列 player_power_uses，每項 {ability_id,manifested}，僅記玩家實際嘗試的超自然能力；未登記 ID 留空，普通動作、工具、假設及提問用 []。manifested 表示任何實際超自然作用，不是是否達成目的；局部熱度、精神壓力、讀取意圖、感知力量或被抵抗的干擾都算 true。沒有回合前來源就完全零作用，不能本輪覺醒或自授能力補造來源。純內在企圖不被 NPC 感知。
changes 只列實際變化，無變化 {}。可用 pc/npcs/locations/abilities/canon/world/contract/item_catalog、facts_add、open_matters。人物及地點用 ID；新個體先有具體基礎再行為並一起保存。保留人格、情緒與關係的因果，不用好感分數。移動、外顯狀況、裝備改變時同步位置、場景與資料；普通裝備記 equipment_notes/inventory。沒改的欄位不重抄。
逐步建立：scene_people 只是在場人物索引，沿用 ID；只有 npcs 的人物載入了詳細資料。酒館等人群先用 locations 的 crowd（簡短背景字串）呈現，不替每名路人寫完整傳記。實際交談才在 changes.npcs 建立穩定個體，detail_level:incidental，具體身分、活動、態度、所知資訊及一項牽掛即可；名字未知可用穩定的外觀稱呼。持續交往才補充為 developed，不能倒造舊行為原因或新能力。群體提問只描寫合理的少數反應者，不逐人模擬。scene_focus 列本輪實際互動的人物 ID；同處酒館不等於聽到所有私語。重要承諾與共同經歷可寫人物 memory_note:{text,evidence}，evidence 摘錄本輪敘事，不編造未發生回憶。
先在 establish.people 建立本輪首次個別接觸的人（背景人群用 []），每人 {id,name,species,role,description,activity,stance,concern,knowledge:[]}，沿用 ID，不重建已存在者。這是先 Establish 再 Portray，同一次生成完成，不要只在長篇 narration 介紹新人物卻不保存紀錄。
新人物只寫 establish.people，不在 changes.npcs 重抄；changes.npcs 只更新舊人物。人物每欄一句短句，敘事約一百二十至二百五十字；不重抄未變欄位。
只回傳 {"player_power_uses":[],"establish":{"people":[]},"narration":"完整故事或 OOC 回覆","changes":{}}。'''

# Same host contract in a shorter form for small local contexts. The original
# RPG OS source excerpts remain verbatim; no extra model call or story summary.
COMPACT_SYSTEM='''依 RPG OS v1.01 Understand→Establish→Resolve→Portray 主持；程式只存檔及核對玩家超自然能力來源。只寫繁體中文自然敘事，名稱中文（English）。完整回答最後 user，保留短句、粵語、否定、OOC、內在意圖與真正台詞的區別；不替玩家添加台詞、感受、行動或選擇。宣告是嘗試，不保證成功。
current_snapshot 是目前資料，其後 user/assistant 為依序發生的歷史；history_index 的地點與 witnesses 限制感知。state_provenance 的版本只表示欄位更新時間，舊值不自動失效；已接受的較新事件優先，不重演歷史。bookkeeping 不完整仍已發生。NPC 只知自己感知的事，不讀玩家內心。
player_power_uses 僅列玩家實際嘗試的超自然能力 {ability_id,manifested}；普通動作、工具、假設、提問用 []。沿用 player_ability_record，無既定來源就零作用，不能本輪覺醒、自授或倒造來源；局部作用、感知、精神壓力或被抵抗也算 manifested:true。未登記 ID 留空。
依人物人格、情緒、關係、所知與代價作自主反應，保留因果、數量、身分、能力、地理、死亡及已發生後果。narration 約一百二十至二百五十字完整故事或 OOC 回覆，不寫技術清單、內部 ID、選項，不要求玩家操作檔案。
changes 只列實際變化，無則 {}；沿用人物與地點 ID，移動、裝備、外顯狀況同步保存。scene_people 是未載入詳情的在場索引，nearby_characters 在鄰處；不可重建、搬人或使遠處人物回應。人群先用地點 crowd 背景；首次個別互動只在 establish.people 建立一至三名 {id,name,species,role,description,activity,stance,concern,knowledge:[]}，每欄短句。原人物更新 changes.npcs；持續交往才 developed。scene_focus 列本輪互動 ID，同處不等於聽到私語。
重要共同經歷可寫人物 memory_note:{text,evidence}；evidence 摘錄本輪敘事，inner_life.memories 是陣列，不能改寫舊事。
只回傳 {"player_power_uses":[],"establish":{"people":[]},"narration":"完整自然回覆","changes":{}}；未變欄位不重抄，資料整理不得混入 narration。'''


def working_people(people, text, memory_limit=6):
    """Remove duplicate archives in every projection, including budget retries."""
    from .scene_memory import recall
    for npc in people.values():
        npc.pop('dialogue',None)
        npc['knowledge']=recall(npc.get('knowledge',[]),text,memory_limit)
        life=npc.get('inner_life',{})
        if isinstance(life,dict):
            if isinstance(life.get('memories'),list):life['memories']=recall(life['memories'],text,memory_limit)
            if isinstance(life.get('personality_history'),list):life['personality_history']=recall(life['personality_history'],text,2)
        npc.pop('player_view',None)
    return people


MEMORY_NOTE={'type':'object','properties':{'text':{'type':'string','minLength':1,'maxLength':240},
    'evidence':{'type':'string','minLength':4,'maxLength':240}},'required':['text','evidence'],'additionalProperties':False}
NPC_PATCH={'type':'object','properties':{
    'detail_level':{'type':'string','enum':['incidental','developed']},
    'memory_note':MEMORY_NOTE,
    **{key:{'type':'string'} for key in ('name','description','location','role','species','public_name','background','goal','equipment_notes')},
    **{key:{'type':'boolean'} for key in ('known','alive')},
    'conditions':{'type':'array','items':{'type':'string'}},
    'knowledge':{'type':'array','items':{'type':'string'}},
    'anchor':{'type':'object','additionalProperties':{'type':'string'}},
    'inventory':{'type':'object','additionalProperties':{'type':'integer','minimum':0}},
    'injuries':{'type':'array','items':{'type':'object','additionalProperties':True}},
    'encounter':{'type':'object','additionalProperties':{'type':'string'}},
    'inner_life':{'type':'object','properties':{
        'personality':{'anyOf':[{'type':'null'},{'type':'object','properties':{
            'description':{'type':'string'},'basis':{'type':'string'},'established_revision':{'type':'integer'}},'additionalProperties':False}]},
        'limits':{'type':'array','items':{'type':'string'}},
        'current_emotions':{'type':'array','maxItems':4,'items':{'type':'string'}},
        'relationships':{'type':'object','additionalProperties':True},
        'personality_history':{'type':'array','items':{'type':'object','additionalProperties':True}},
        'memories':{'type':'array','items':{'anyOf':[{'type':'string'},{'type':'object','additionalProperties':True}]}}},
        'additionalProperties':False}},'additionalProperties':False}
SCHEMA={'type':'object','properties':{
    'player_power_uses':{'type':'array','maxItems':8,'items':{'type':'object','properties':{
        'ability_id':{'type':'string','maxLength':120},'manifested':{'type':'boolean','description':'Any supernatural effect occurred, even partial pressure, detection, interference or resisted control. False means zero supernatural effect, not merely failure to achieve the goal.'}},
        'required':['ability_id','manifested'],'additionalProperties':False}},
    'narration':{'type':'string','minLength':1,'maxLength':5000},
    'changes':{'type':'object','properties':{
        **{key:{'type':'object','additionalProperties':True} for key in ('pc','canon','world','contract')},
        'npcs':{'type':'object','additionalProperties':NPC_PATCH},
        'scene_focus':{'type':'array','maxItems':8,'items':{'type':'string'}},
        **{key:{'type':'object','additionalProperties':{'type':'object','additionalProperties':True}}
           for key in ('locations','abilities','item_catalog')},
        'facts_add':{'type':'array','items':{'anyOf':[{'type':'string'},{'type':'object','additionalProperties':True}]}},
        'open_matters':{'type':'array','items':{'type':'string'}}},'additionalProperties':False}},
    'required':['player_power_uses','narration','changes'],'additionalProperties':False}

NEW_PERSON={'type':'object','properties':{
    **{key:{'type':'string','minLength':1,'maxLength':160} for key in ('id','name','species','role','description','activity','stance','concern')},
    'knowledge':{'type':'array','maxItems':4,'items':{'type':'string','maxLength':160}}},
    'required':['id','name','species','role','description','activity','stance','concern','knowledge'],'additionalProperties':False}
from .world_schema import BILINGUAL_NAME
NEW_PERSON['properties']['name']=dict(BILINGUAL_NAME)
SCHEMA['properties']={key:value for key,value in [
    ('player_power_uses',SCHEMA['properties']['player_power_uses']),
    ('establish',{'type':'object','properties':{'people':{'type':'array','maxItems':3,'items':NEW_PERSON}},
        'required':['people'],'additionalProperties':False}),
    ('narration',SCHEMA['properties']['narration']),('changes',SCHEMA['properties']['changes'])]}
SCHEMA['required']=['player_power_uses','establish','narration','changes']


def reply_schema(state):
    """Keep storage field names precise while allowing partial existing edits."""
    schema=copy.deepcopy(SCHEMA)
    schema['$defs']={'npc_update':copy.deepcopy(NPC_PATCH)}
    people=schema['properties']['changes']['properties']['npcs']
    new_ids=[f'npc_{state["revision"]+1}_{i}' for i in range(1,4)]
    people['properties']={key:{'$ref':'#/$defs/npc_update'} for key in [*state['npcs'],*new_ids]}
    people['additionalProperties']=False
    schema['properties']['establish']['properties']['people']['items']['properties']['id']={
        'type':'string','enum':new_ids}
    identity=state.get('canon',{}).get('actors',{}).get(state['pc']['id'],{})
    ids=list(dict.fromkeys([*state['pc'].get('spells',[]),*identity.get('powers',[]),'']))
    schema['properties']['player_power_uses']['items']['properties']['ability_id']={'type':'string','enum':ids}
    return schema


def establish_details(state,result):
    """Fold typed pre-narrative foundations into the existing storage delta."""
    result=copy.deepcopy(result);foundation=result.pop('establish',None)
    if not isinstance(foundation,dict):return result
    changes=result['changes'];npcs=changes.setdefault('npcs',{})
    if not isinstance(npcs,dict):return result
    people=foundation.get('people',[]);established=set()
    for person in people[:3] if isinstance(people,list) else []:
        if not isinstance(person,dict) or set(person)!=set(NEW_PERSON['properties']):continue
        if any(not isinstance(person[key],str) or not person[key].strip() for key in set(person)-{'knowledge'}):continue
        key=person['id']
        if key in state['npcs'] or key==state['pc']['id'] or not isinstance(person['knowledge'],list):continue
        if any(person['name'].casefold()==npc['name'].casefold() for npc in state['npcs'].values()):continue
        if any(not isinstance(value,str) for value in person['knowledge']):continue
        base={field:person[field] for field in ('name','species','role','description','knowledge')}
        base.update(location=state['pc']['location'],detail_level='incidental',known=True,alive=True,
            anchor={'concern':person['concern']},encounter={'condition':person['activity'],'stance':person['stance']})
        patch=npcs.get(key,{})
        if isinstance(patch,dict):npcs[key]=merge(base,patch);established.add(key)
    # Allocated IDs also allow a newly learned name/condition to be recorded
    # after the dialogue; an unused slot is never itself a fictional person.
    changes['npcs']={key:value for key,value in npcs.items() if key in state['npcs'] or key in established}
    return result


def _incomplete_header(text):
    """Recover whole leading fields only, never partial values or a second root."""
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate key')
            result[key]=value
        return result
    decoder=json.JSONDecoder(object_pairs_hook=pairs)
    try:decoder.raw_decode(text);return {}  # A whole first root is ambiguous here.
    except ValueError:pass
    if not text.startswith('{'):return {}
    position=1;fields={}
    try:
        while True:
            position+=len(text[position:])-len(text[position:].lstrip())
            key,end=decoder.raw_decode(text,position)
            if not isinstance(key,str) or key in fields:return {}
            position=end+len(text[end:])-len(text[end:].lstrip())
            if text[position]!=':':return {}
            position+=1
            position+=len(text[position:])-len(text[position:].lstrip())
            value,position=decoder.raw_decode(text,position);fields[key]=value
            if key=='narration':return fields
            position+=len(text[position:])-len(text[position:].lstrip())
            if text[position]!=',':return {}
            position+=1
    except (ValueError,IndexError):return {}


def decode_reply(raw):
    def structured(text):return text.startswith(('{','[')) or bool(re.match(r'^```(?:json)?\s*[{\[]',text,re.I))
    if isinstance(raw,dict):value=raw
    elif isinstance(raw,str):
        text=raw.strip()
        clean=story_text(text)
        if clean!=text and not structured(text):
            if clean:return {'narration':clean,'changes':{},'bookkeeping':'incomplete'}
            raise RuleError('模型這次沒有提供文字回覆。')
        try:
            from .model import parse_proposal
            value=parse_proposal(text)
        except RuleError:
            # Even a truncated metadata tail must not throw away the complete
            # story field that preceded it. Do not invent or repair its words.
            match=re.search(r'"narration"\s*:\s*',text)
            if match:
                try:
                    narrative,_=json.JSONDecoder().raw_decode(text[match.end():])
                    if isinstance(narrative,str) and story_text(narrative).strip():
                        head=_incomplete_header(text)
                        return {'narration':story_text(narrative),'changes':{},'bookkeeping':'incomplete',
                            'establish':head.get('establish'),'player_power_uses':head.get('player_power_uses',[])}
                except (ValueError,TypeError):pass
            if structured(text):
                raise RuleError('這次故事回覆尚未完成，進度仍保留，請再試一次。')
            clean=story_text(text)
            if clean:return {'narration':clean,'changes':{},'bookkeeping':'plain_reply'}
            raise RuleError('模型這次沒有回覆，故事尚未改變。請確認模型連線後再試。')
    else:raise RuleError('模型這次沒有提供文字回覆。')
    narrative=story_text(value.get('narration')) if isinstance(value,dict) else None
    if not isinstance(narrative,str) or not narrative.strip():
        if isinstance(raw,str) and not structured(raw.strip()) and story_text(raw.strip()):
            return {'narration':story_text(raw.strip()),'changes':{},'bookkeeping':'plain_reply'}
        raise RuleError('模型這次沒有提供文字回覆。')
    changes=value.get('changes',{})
    return {'narration':narrative,'changes':changes if isinstance(changes,dict) else {},
            'establish':value.get('establish'),
            'player_power_uses':value.get('player_power_uses',[]),
            'bookkeeping':'ready' if isinstance(changes,dict) else 'incomplete'}


def reply(state,text,base_url,recent=None,state_provenance=None):
    from .model import _complete
    from .progress import stage
    original=require_text(text,'你的行動或台詞')
    context=copy.deepcopy(state)
    # Full plans stay on disk. Retrieve only the current chapter and relevant
    # opportunities, rather than repeatedly feeding the entire future story.
    context.pop('story',None)
    identity=state.get('canon',{}).get('actors',{}).get(state['pc']['id'],{})
    for field in ('role','species'):
        if field in identity:context['pc'].setdefault(field,identity[field])
    # Expose the already established record directly; do not ask the model to
    # reconstruct ownership from recent narration or the player's declaration.
    power_ids=identity.get('powers',[])
    context['player_ability_record']={
        'learned_spells':copy.deepcopy(state['pc'].get('spells',[])),
        'registered_powers':copy.deepcopy(power_ids),
        'spell_definitions':{key:copy.deepcopy(state.get('abilities',{}).get(key)) for key in state['pc'].get('spells',[])},
        'power_definitions':{key:copy.deepcopy(state.get('canon',{}).get('powers',{}).get(key)) for key in power_ids},
        'ordinary_capabilities':copy.deepcopy(state['pc'].get('capabilities',[])),
        'scope':'這是已建立的能力與來源紀錄。玩家宣告是嘗試，不會自行新增能力；先前回覆寫出的效果也不能倒造其來源。未建立的能力須依 RPG OS 的 Establish 程序處理，再解算是否能使用。'}
    from .scene_memory import project,recall
    context.update(project(state,original))
    context.pop('scene_memory',None)
    working_people(context['npcs'],original)
    from .references import referenced_characters
    context['referenced_characters']=referenced_characters(state,{'text':original})
    # The complete geography remains persistent. Distant descriptions are only
    # retrieved when named; IDs, names and routes keep the world's layout fixed.
    from .references import name_options
    near={state['pc']['location'],*state['locations'][state['pc']['location']]['exits']}
    for key,place in context['locations'].items():
        place.pop('source',None)
        place['exits']={target:{field:value for field,value in route.items() if field in ('known','clear','obstruction')} for target,route in place['exits'].items()}
        if key not in near and not any(name.casefold() in original.casefold() for name in name_options(state,key,place)):
            context['locations'][key]={field:place[field] for field in ('name','exits')}
    active_ids={state['pc']['id'],*context['npcs']}
    if 'canon' in context:
        context['canon']['actors']={key:value for key,value in context['canon']['actors'].items() if key in active_ids}
        context['canon']['powers']={key:value for key,value in context['canon']['powers'].items() if value.get('actor') in active_ids}
        context['canon']['uses']=context['canon'].get('uses',[])[-4:]
    context['facts']=recall(context.get('facts',[]),original,12)
    for key in ('media','people_notes'):context.pop(key,None)
    for item in context.get('item_catalog',{}).values():
        if isinstance(item,dict):item.pop('source',None)
    if 'world' in context:context['world']={key:context['world'][key] for key in ('background','rules') if key in context['world']}
    # Equipment and current encounter fields describe today; opening prose is
    # only a baseline. Give the GM provenance rather than a stale dialogue task.
    context['host_mode']='RPG OS GM; pre-turn player supernatural ability source check; no general gameplay approval'
    past=[{**row,'narration':story_text(row['narration'])} for row in recent or []
          if isinstance(row,dict) and isinstance(row.get('narration'),str)]
    # Use one system message for local chat-template compatibility. Put the
    # response contract after the reference material, rather than letting the
    # document/table format become the model's last example of an answer.
    instructions=SYSTEM
    def compose(rows):
        history_index=[{key:row[key] for key in ('revision','location','witnesses','bookkeeping') if key in row} for row in rows]
        snapshot=json.dumps({'current_snapshot':context,
                             'state_provenance':state_provenance or {'snapshot_revision':state['revision']},
                             'history_index':history_index},ensure_ascii=False,separators=(',',':'))
        messages=[{'role':'system','content':rules_packet()+'\n\n本回合狀態資料：\n'+snapshot+
                   '\n\n主持與輸出要求：\n'+instructions+
                   '\n只在 narration 寫給玩家的自然回覆，沿用已確立的數量、人物及事實。資料整理放 changes；不要在 narration 列出 current_snapshot、state_provenance、history_index、內部 ID、技術清單或下一步選項。'}]
        for row in rows:
            messages.append({'role':'user','content':row.get('declaration','') or '【先前已發生的場景紀錄，沒有新的玩家宣告】'})
            messages.append({'role':'assistant','content':row['narration']})
        messages.append({'role':'user','content':original})
        return messages
    messages=compose(past)
    from .context_budget import budget,count
    output_max=1500
    limit=budget(base_url,output_max)
    if limit:
        measured=count(base_url,messages)
        if measured is not None and measured>limit:
            # Compact repeated host guidance before discarding actual dialogue.
            instructions=COMPACT_SYSTEM
            messages=compose(past);measured=count(base_url,messages)
        # On an 8K backend keep the latest complete exchange before reserving
        # a long metadata tail. This is still one generation, never a summary call.
        if measured is not None and measured>limit and past:
            last_size=count(base_url,compose(past[-1:]))
            smaller=budget(base_url,1200)
            if last_size is not None and smaller and last_size<=smaller:
                output_max=1200;limit=smaller
        # Keep the latest exchange while shrinking duplicate state. Dropping it
        # first made even a short follow-up lose the dialogue it depended on.
        while measured is not None and measured>limit and len(past)>1:
            past=past[1:];messages=compose(past);measured=count(base_url,messages)
        if measured is not None and measured>limit:
            context['scene_people']=dict(list(context.get('scene_people',{}).items())[:6])
            for npc in context['npcs'].values():
                life=npc.get('inner_life',{})
                if isinstance(life,dict) and isinstance(life.get('memories'),list):life['memories']=recall(life['memories'],original,2)
            messages=compose(past);measured=count(base_url,messages)
        for maximum in (2,1):
            if measured is None or measured<=limit:break
            # A small local context can require fewer full profiles than the
            # normal working set. Explicitly named people remain prioritized.
            smaller=project(state,original,full_limit=maximum,index_limit=4)
            for key in ('npcs','scene_people','scene_scope'):context[key]=smaller[key]
            working_people(context['npcs'],original,2)
            if 'canon' in context:
                keep={state['pc']['id'],*context['npcs']}
                context['canon']['actors']={key:value for key,value in context['canon']['actors'].items() if key in keep}
                context['canon']['powers']={key:value for key,value in context['canon']['powers'].items() if value.get('actor') in keep}
            messages=compose(past);measured=count(base_url,messages)
        if measured is not None and measured>limit and output_max>1200:
            smaller=budget(base_url,1200)
            if smaller and smaller>limit:
                output_max=1200;limit=smaller
        if measured is not None and measured>limit and past:
            # Last resort for unusually long previous replies; saved originals
            # are unchanged and the current player's input is never truncated.
            past=[];messages=compose(past);measured=count(base_url,messages)
        if measured is not None and measured>limit:
            raise RuleError('本機模型的上下文空間仍不足，這次行動尚未執行，故事已保留。可縮短輸入或增加模型的上下文容量後重試。')
    with stage('RPG OS 主持與敘事'):
        raw=_complete(messages,base_url,output_max,.45,response_schema=reply_schema(state),raw=True)
    result=establish_details(state,decode_reply(raw))
    from .ability_sources import inspect_reply
    issues,checked=inspect_reply(state,result)
    if not issues:
        result['ability_source_check']=checked
        return result
    # The unaccepted draft and its changes are never written or replayed as
    # history. A single correction keeps the entire original declaration.
    corrected_messages=copy.deepcopy(messages)
    corrected_messages[0]['content']+='\n\n已核對的能力來源結果：\n'+json.dumps(issues,ensure_ascii=False)+'''
上面的能力沒有可用來源，相關嘗試完全不產生超自然效果，包括任何局部作用、精神壓力、能量波動、思想干擾、讀心、感知力量或強迫感。不能寫成「有力量但對方抵抗／尚未完全受控」；沒有來源就是連這些作用都沒有。只有玩家真正說出口的話或外顯行為可被 NPC 察覺，純內在意圖不會被讀取。依這個結果重新裁定本次完整原句的普通部分與 NPC 自主反應，不新增或覺醒能力，不把力量失敗改成 NPC 自動服從，不補寫來源，不複製過往錯誤效果。直接正常敘事，不向玩家顯示技術警告。'''
    with stage('依能力來源修正敘事'):
        raw=_complete(corrected_messages,base_url,output_max,.35,response_schema=reply_schema(state),raw=True)
    corrected=establish_details(state,decode_reply(raw))
    remaining,checked=inspect_reply(state,corrected)
    if remaining:
        # Never loop, reroll NPC choices, or persist the unsupported effect.
        return {'narration':'你嘗試施展尚未掌握的超自然能力，但沒有產生相應效果。',
                'changes':{},'player_power_uses':[],'bookkeeping':'incomplete',
                'ability_source_check':issues,'ability_source_correction':True}
    corrected['ability_source_check']=[*issues,*checked]
    corrected['ability_source_correction']=True
    return corrected


def merge(base, patch):
    result=copy.deepcopy(base)
    for key,value in patch.items():
        if isinstance(value,dict) and isinstance(result.get(key),dict):result[key]=merge(result[key],value)
        else:result[key]=copy.deepcopy(value)
    return result


def record_changes(state,changes,revision,narration=''):
    """Structural storage checks only; no world/rules/intent adjudication."""
    from .portable import validate_state
    after=copy.deepcopy(state)
    if not isinstance(changes,dict):return after,'incomplete'
    partial=False;memory_notes={}
    for key in ('pc','npcs','locations','abilities','canon','world','contract','item_catalog'):
        if key in changes:
            if not isinstance(changes[key],dict):partial=True;continue
            patch=changes[key]
            if key in ('npcs','locations','abilities','item_catalog'):
                clean={name:value for name,value in patch.items() if isinstance(value,dict)}
                partial=partial or len(clean)!=len(patch)
                patch=clean
            if key=='npcs':
                # A display field accidentally nested in the ID map must never
                # create a fictional person named after that field.
                patch={name:value for name,value in patch.items() if name!='player_view'}
                memory_notes={name:value['memory_note'] for name,value in patch.items() if 'memory_note' in value}
                patch={name:{field:value for field,value in npc.items() if field not in ('player_view','memory_note')} for name,npc in patch.items()}
                for name,npc in patch.items():
                    if 'encounter' in npc:
                        encounter=npc['encounter']
                        if isinstance(encounter,dict):
                            clean={}
                            for field,value in encounter.items():
                                if isinstance(value,dict) and set(value)<={'text','evidence'} and isinstance(value.get('text'),str):value=value['text']
                                if isinstance(value,str):clean[field]=value
                                else:partial=True
                            npc['encounter']=clean
                        else:npc.pop('encounter');partial=True
                    if isinstance(npc.get('knowledge'),list):
                        old=state['npcs'].get(name,{}).get('knowledge',[])
                        if isinstance(old,list):
                            combined=[];seen=set()
                            for item in [*old,*npc['knowledge']]:
                                fingerprint=json.dumps(item,ensure_ascii=False,sort_keys=True)
                                if fingerprint not in seen:combined.append(copy.deepcopy(item));seen.add(fingerprint)
                            npc['knowledge']=combined
                    life=npc.get('inner_life',{})
                    previous=state['npcs'].get(name,{}).get('inner_life',{})
                    if isinstance(life,dict) and isinstance(life.get('memories'),list) and isinstance(previous,dict) and isinstance(previous.get('memories'),list):
                        # The model only sees a selection. A returned selection
                        # cannot replace the full durable lifetime record.
                        combined=[];seen=set()
                        for memory in [*previous['memories'],*life['memories']]:
                            fingerprint=json.dumps(memory,ensure_ascii=False,sort_keys=True)
                            if fingerprint not in seen:combined.append(copy.deepcopy(memory));seen.add(fingerprint)
                        npc['inner_life']={**life,'memories':combined}
            after[key]=merge(after.get(key,{}),patch)
    if 'open_matters' in changes:
        after['open_matters']=copy.deepcopy(changes['open_matters'])
    facts=changes.get('facts_add',[])
    if not isinstance(facts,list):return copy.deepcopy(state),'incomplete'
    for fact in facts:
        if isinstance(fact,str):fact={'text':fact,'visibility':'public'}
        if not isinstance(fact,dict):return copy.deepcopy(state),'incomplete'
        after['facts'].append({'visibility':'public',**copy.deepcopy(fact),'source':'rpg-os-gm:'+str(revision)})
    # New records get data-shape defaults, not a second authoring approval.
    for key,npc in after['npcs'].items():
        if not isinstance(npc,dict):return copy.deepcopy(state),'incomplete'
        defaults={'id':key,'name':key,'description':'','location':after['pc']['location'],'known':True,'alive':True,
                  'detail_level':'established' if key in state['npcs'] else 'incidental',
                  'anchor':{},'encounter':{'condition':'','priorities':'','appraisal':'','attraction':'','stance':''},
                  'knowledge':[],'conditions':[],
                  'inner_life':{'personality':None,'limits':[],'current_emotions':[],'relationships':{},'memories':[],'personality_history':[]}}
        after['npcs'][key]=merge(defaults,npc)
    def normalize(value):return re.sub(r'\s+','',unicodedata.normalize('NFKC',value))
    for key,note in memory_notes.items():
        if key not in after['npcs'] or not isinstance(note,dict):continue
        text=note.get('text');evidence=note.get('evidence')
        if not isinstance(text,str) or not 1<=len(text)<=240 or not isinstance(evidence,str) or len(normalize(evidence))<4 or normalize(evidence) not in normalize(narration):continue
        npc=after['npcs'][key]
        if npc['location']!=after['pc']['location']:continue
        life=npc.get('inner_life',{})
        if not isinstance(life,dict) or not isinstance(life.get('memories',[]),list):continue
        memories=life.setdefault('memories',[])
        if not any(isinstance(row,dict) and row.get('text')==text for row in memories):
            memories.append({'text':text,'evidence':evidence,'revision':revision,'source':'experienced_scene'})
    if 'canon' in after:
        for who,actor in [(after['pc']['id'],after['pc']),*after['npcs'].items()]:
            if who not in after['canon']['actors']:
                after['canon']['actors'][who]={'species':actor.get('species','未記錄'),'role':actor.get('role','未記錄'),
                    'forms':{'base':actor.get('description','目前形態')},'current_form':'base','powers':[],
                    'source':'RPG OS 主持建立','established_revision':revision}
    from .scene_memory import remember
    remember(state,after,changes,narration,revision)
    after['revision']=revision
    try:validate_state(after)
    except (RuleError,ValueError,TypeError,KeyError):return copy.deepcopy(state),'incomplete'
    return after,'partial' if partial else 'ready'
