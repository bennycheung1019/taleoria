"""RPG OS GM owns play. The host stores replies and structurally usable data.

No input classifier, keyword adjudication, or general narrative veto is used.
Player supernatural effects have the user's narrowly authorized source check.
Malformed bookkeeping never rejects a delivered story.
"""
import copy
import json
import re
from .engine import RuleError, require_text
from .rulebook import verified_sources, section


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
公開人物筆記用 changes.player_view，與 npcs 並列，例如 {"player_view":{"hark":{"facts":{"family":{"text":"他說自己有弟弟。","kind":"said","evidence":"我家有一個弟弟"}},"relationship":{"text":"他願意繼續交談。","evidence":"我們可以繼續談談"}}}}。facts 用固定主題鍵更新背景或性格；relationship/condition 用 {text,evidence} 簡述可察覺的關係或狀況。evidence 必須摘錄本次 narration 至少四字。只存玩家已學內容，不公開私人內心、不代定玩家感情；沒變就省略。只有公開筆記用 text/evidence；內部 encounter 各值仍是字串，inner_life.memories 是陣列。
story_director 是私密規劃，低於 RPG OS 與真實現況。機會只在探索時選用；不催日常、不重送拒絕的線索、不搬人搬地、授予力量、復活或取消後果。可拒絕、繞路、跳章或改變終局。抵達後沿用 nearby_characters 的固定人物，不把原地人物帶去替換；實際遇見才設 known:true。真相不自動成為 NPC 所知。
進展才填 changes.story_update：chapter 為章節 ID，opportunities 為機會 ID 對 presented/followed/declined/lost 的物件，revealed 列真相 ID，status 可 active/paused/resolved/abandoned。summary 記因果，evidence 摘錄 narration 至少四字；未發生不推進。
只回傳 {"player_power_uses":[],"narration":"完整故事或 OOC 回覆","changes":{}}。'''


PUBLIC_NOTE={'type':'object','properties':{'text':{'type':'string','minLength':1,'maxLength':240},
    'evidence':{'type':'string','minLength':4,'maxLength':240}},'required':['text','evidence'],'additionalProperties':False}
PUBLIC_VIEW={'type':'object','properties':{
    'facts':{'type':'object','additionalProperties':{'type':'object','properties':{
        **PUBLIC_NOTE['properties'],'kind':{'type':'string','enum':['said','observed']}},
        'required':['text','kind','evidence'],'additionalProperties':False}},
    'relationship':PUBLIC_NOTE,'condition':PUBLIC_NOTE},'additionalProperties':False}
NPC_PATCH={'type':'object','properties':{
    'player_view':PUBLIC_VIEW,
    **{key:{'type':'string'} for key in ('name','description','location','role','species','public_name')},
    **{key:{'type':'boolean'} for key in ('known','alive')},
    'conditions':{'type':'array','items':{'type':'string'}},
    'encounter':{'type':'object','additionalProperties':{'type':'string'}},
    'inner_life':{'type':'object','properties':{
        'memories':{'type':'array','items':{'anyOf':[{'type':'string'},{'type':'object','additionalProperties':True}]}}},
        'additionalProperties':True}},'additionalProperties':True}
SCHEMA={'type':'object','properties':{
    'player_power_uses':{'type':'array','maxItems':8,'items':{'type':'object','properties':{
        'ability_id':{'type':'string','maxLength':120},'manifested':{'type':'boolean','description':'Any supernatural effect occurred, even partial pressure, detection, interference or resisted control. False means zero supernatural effect, not merely failure to achieve the goal.'}},
        'required':['ability_id','manifested'],'additionalProperties':False}},
    'narration':{'type':'string','minLength':1,'maxLength':5000},
    'changes':{'type':'object','properties':{
        **{key:{'type':'object','additionalProperties':True} for key in ('pc','canon','world','contract')},
        'npcs':{'type':'object','additionalProperties':NPC_PATCH},
        'player_view':{'type':'object','additionalProperties':PUBLIC_VIEW},
        'story_update':{'type':'object','properties':{
            'chapter':{'type':'string'},'opportunities':{'type':'object','additionalProperties':{'type':'string','enum':['presented','followed','declined','lost']}},
            'revealed':{'type':'array','items':{'type':'string'}},'status':{'type':'string','enum':['active','paused','resolved','abandoned']},
            'summary':{'type':'string','maxLength':240},'evidence':{'type':'string','minLength':4,'maxLength':240}},
            'required':['evidence'],'additionalProperties':False},
        **{key:{'type':'object','additionalProperties':{'type':'object','additionalProperties':True}}
           for key in ('locations','abilities','item_catalog')},
        'facts_add':{'type':'array','items':{'anyOf':[{'type':'string'},{'type':'object','additionalProperties':True}]}},
        'open_matters':{'type':'array','items':{'type':'string'}}},'additionalProperties':False}},
    'required':['player_power_uses','narration','changes'],'additionalProperties':False}


def decode_reply(raw):
    if isinstance(raw,dict):value=raw
    elif isinstance(raw,str):
        text=raw.strip()
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
                    if isinstance(narrative,str) and narrative.strip():
                        return {'narration':narrative,'changes':{},'bookkeeping':'incomplete'}
                except (ValueError,TypeError):pass
            if text:return {'narration':text,'changes':{},'bookkeeping':'plain_reply'}
            raise RuleError('模型這次沒有回覆，故事尚未改變。請確認模型連線後再試。')
    else:raise RuleError('模型這次沒有提供文字回覆。')
    narrative=value.get('narration') if isinstance(value,dict) else None
    if not isinstance(narrative,str) or not narrative.strip():
        if isinstance(raw,str) and raw.strip():return {'narration':raw.strip(),'changes':{},'bookkeeping':'plain_reply'}
        raise RuleError('模型這次沒有提供文字回覆。')
    changes=value.get('changes',{})
    return {'narration':narrative,'changes':changes if isinstance(changes,dict) else {},
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
    from .story_director import context as director_context
    director=director_context(state)
    if director:context['story_director']=director
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
    context['npcs']={key:value for key,value in context['npcs'].items()
                     if value.get('location')==state['pc']['location']}
    for npc in context['npcs'].values():
        life=npc.get('inner_life',{})
        if isinstance(life,dict) and isinstance(life.get('memories'),list):life['memories']=life['memories'][-6:]
        npc.pop('dialogue',None)  # Exact recent exchanges are provided separately.
        profile=npc.get('player_view',{})
        if isinstance(profile,dict):
            if isinstance(profile.get('facts'),dict):profile['facts']={key:{field:value for field,value in note.items() if field in ('text','kind')} for key,note in profile['facts'].items()}
            for field in ('relationship','condition'):
                if isinstance(profile.get(field),dict):profile[field]={'text':profile[field]['text']}
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
    if state.get('story'):
        context['nearby_characters']={key:{'name':npc['name'],'location':npc['location'],'alive':npc['alive'],
            'description':npc['description'],'personality':npc.get('inner_life',{}).get('personality',{}).get('description'),
            'anchor':npc.get('anchor',{}),'activity':npc.get('encounter',{}).get('condition'),
            'knowledge':npc.get('knowledge',[])[:4]}
            for key,npc in state['npcs'].items() if npc['location'] in near and npc['location']!=state['pc']['location']}
        # Remote canonical detail is retrieved when relevant; the nearby index
        # supplies fixed identities without duplicating full private profiles.
        active_ids={state['pc']['id'],*context['npcs']}
        if 'canon' in context:
            context['canon']['actors']={key:value for key,value in context['canon']['actors'].items() if key in active_ids}
            context['canon']['powers']={key:value for key,value in context['canon']['powers'].items() if value.get('actor') in active_ids}
    context['facts']=context.get('facts',[])[-12:]
    for key in ('media','people_notes'):context.pop(key,None)
    for item in context.get('item_catalog',{}).values():
        if isinstance(item,dict):item.pop('source',None)
    if 'world' in context:context['world']={key:context['world'][key] for key in ('background','rules') if key in context['world']}
    # Equipment and current encounter fields describe today; opening prose is
    # only a baseline. Give the GM provenance rather than a stale dialogue task.
    context['host_mode']='RPG OS GM; pre-turn player supernatural ability source check; no general gameplay approval'
    past=[row for row in recent or [] if isinstance(row,dict) and isinstance(row.get('narration'),str)]
    # Use one system message for local chat-template compatibility. Put the
    # response contract after the reference material, rather than letting the
    # document/table format become the model's last example of an answer.
    def compose(rows):
        history_index=[{key:row[key] for key in ('revision','location','witnesses','bookkeeping') if key in row} for row in rows]
        snapshot=json.dumps({'current_snapshot':context,
                             'state_provenance':state_provenance or {'snapshot_revision':state['revision']},
                             'history_index':history_index},ensure_ascii=False,separators=(',',':'))
        messages=[{'role':'system','content':rules_packet()+'\n\n本回合狀態資料：\n'+snapshot+
                   '\n\n主持與輸出要求：\n'+SYSTEM+
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
        if measured is not None and measured>limit and director:
            # Prefer the live scene and recent dialogue to distant plot notes.
            compact={key:value for key,value in director.items() if key not in ('authority','ending_conflict','established_threads','chapters')}
            compact['chapter']={key:value for key,value in compact['chapter'].items() if key!='outcomes'}
            compact['progress']={key:value for key,value in compact['progress'].items() if key in ('chapter','status','revealed','opportunities')}
            context['story_director']=compact;messages=compose(past);measured=count(base_url,messages)
        # On an 8K backend keep the latest complete exchange before reserving
        # a long metadata tail. This is still one generation, never a summary call.
        if measured is not None and measured>limit and past:
            last_size=count(base_url,compose(past[-1:]))
            smaller=budget(base_url,1200)
            if last_size is not None and smaller and last_size<=smaller:
                output_max=1200;limit=smaller
        while measured is not None and measured>limit and past:
            past=past[1:];messages=compose(past);measured=count(base_url,messages)
        if measured is not None and measured>limit and 'story_director' in context:
            # Keep truths and usable progress IDs even on a crowded turn.
            core=context['story_director']
            context['story_director']={key:value for key,value in core.items() if key in ('fixed_truths','central_conflict','chapter','actor_reality','opportunities','progress')}
            messages=compose(past)
    with stage('RPG OS 主持與敘事'):
        raw=_complete(messages,base_url,output_max,.45,response_schema=SCHEMA,raw=True)
    result=decode_reply(raw)
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
        raw=_complete(corrected_messages,base_url,output_max,.35,response_schema=SCHEMA,raw=True)
    corrected=decode_reply(raw)
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
    partial=False;public_patches={}
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
                patch={name:value for name,value in patch.items() if name not in ('player_view','story_update')}
                public_patches={name:value['player_view'] for name,value in patch.items() if 'player_view' in value}
                patch={name:{field:value for field,value in npc.items() if field!='player_view'} for name,npc in patch.items()}
            after[key]=merge(after.get(key,{}),patch)
    if 'open_matters' in changes:
        after['open_matters']=copy.deepcopy(changes['open_matters'])
    facts=changes.get('facts_add',[])
    if not isinstance(facts,list):return copy.deepcopy(state),'incomplete'
    for fact in facts:
        if isinstance(fact,str):fact={'text':fact,'visibility':'public'}
        if not isinstance(fact,dict):return copy.deepcopy(state),'incomplete'
        after['facts'].append({**copy.deepcopy(fact),'source':'rpg-os-gm:'+str(revision)})
    # New records get data-shape defaults, not a second authoring approval.
    for key,npc in after['npcs'].items():
        if not isinstance(npc,dict):return copy.deepcopy(state),'incomplete'
        defaults={'id':key,'name':key,'description':'','location':after['pc']['location'],'known':True,'alive':True,
                  'anchor':{},'encounter':{'condition':'','priorities':'','appraisal':'','attraction':'','stance':''},
                  'knowledge':[],'conditions':[],
                  'inner_life':{'personality':None,'limits':[],'current_emotions':[],'relationships':{},'memories':[],'personality_history':[]}}
        after['npcs'][key]=merge(defaults,npc)
    if 'canon' in after:
        for who,actor in [(after['pc']['id'],after['pc']),*after['npcs'].items()]:
            if who not in after['canon']['actors']:
                after['canon']['actors'][who]={'species':actor.get('species','未記錄'),'role':actor.get('role','未記錄'),
                    'forms':{'base':actor.get('description','目前形態')},'current_form':'base','powers':[],
                    'source':'RPG OS 主持建立','established_revision':revision}
    from .player_cards import apply_updates
    if isinstance(changes.get('player_view'),dict):public_patches.update(changes['player_view'])
    apply_updates(state,after,public_patches,narration,revision)
    from .story_director import apply_update as update_story
    update_story(state,after,changes.get('story_update'),narration,revision)
    after['revision']=revision
    try:validate_state(after)
    except (RuleError,ValueError,TypeError,KeyError):return copy.deepcopy(state),'incomplete'
    return after,'partial' if partial else 'ready'
