"""Bounded ordinary physical consequences; no combat scores or automatic hits."""
import re

ATTACK=re.compile(r'刺|捅|砍|斬|踢|揍|毆|勒|掐|摔|殺|攻擊|打(?:他|她|你|哈克|一拳)|\b(?:stab|attack|hit|punch|kick|slash|slice|slit|shoot|strike|choke|kill)\b|\bcut\s+(?:across|through).{0,40}\b(?:neck|throat)\b',re.I)
NPC_WEAPONS={'short_sword':'短劍','long_sword':'長劍','dagger':'匕首','knife':'獵刀','spear':'長矛','club':'木棍'}
WOUND=re.compile(r'(?:受|刺|刀|劍|割|擦|重|輕|挫|灼|燒)傷|傷勢|出血|流血|傷口|中刀|中劍|骨折|昏迷|失去意識|死亡|身亡')


def has_wound(value):
    for match in WOUND.finditer(value):
        prefix=re.split(r'[，,。；;]',value[:match.start()])[-1]
        if re.search(r'(?:沒有|並未|尚未|未|不會|不想|避免|害怕|擔心|可能|恐怕|差點)[^，,。；;]{0,5}$',prefix):continue
        if re.search(r'心理|心靈|情緒',prefix):continue
        return True
    return False


def attacking(action):
    understanding=action.get('understanding')
    text='\n'.join(understanding['actions']) if understanding else action['text']
    if action['kind'] in {'speak','observe','wait','travel','cast'}:return False
    if re.match(r'^(?:我)?(?:心想|想像|想象|幻想|夢到|假設|考慮|思考)|^\s*(?:I\s+(?:think|imagine|dream)|what\s+if|suppose)\b',text,re.I):return False
    return bool(ATTACK.search(text))


def ordinary_exchange(state,action):
    if not attacking(action) or action.get('target') not in state['npcs']:return False
    canon=state.get('canon',{});identities=canon.get('actors',{})
    for who in (state['pc']['id'],action['target']):
        identity=identities.get(who,{})
        if identity.get('species','').lower() not in {'人類','human'} or identity.get('current_form') not in {'human','base'} or identity.get('powers'):return False
    return True


def weapons(state,actor):
    if actor==state['pc']['id']:
        return {key:state.get('item_catalog',{}).get(key,{}).get('name',{'hunting_knife':'普通獵刀','rain_cloak':'雨斗篷','rope':'繩索'}.get(key,key))
                for key,count in state['pc']['inventory'].items() if count>0}
    npc=state['npcs'].get(actor,{})
    description=npc.get('description','')
    return {key:name for key,name in NPC_WEAPONS.items()
            if re.search(r'(?<!沒有)(?<!不再)(?<!未)(?<!沒)(?<!不)(?:佩|持|握|拿|裝備)(?:著|着|有|帶)?(?:一把|一柄|普通|鋼製|鐵製|的|\s){0,3}'+re.escape(name),description)}


def hostile(actor):
    stance=actor.get('encounter',{}).get('stance','')+' '+actor.get('encounter',{}).get('condition','')
    return bool(re.search(r'(?<!不)(?<!未)(?<!非)(?<!沒有)(?:正在交戰|已經交戰|明確敵對|準備攻擊|正在攻擊|持劍相向|openly hostile|in combat)',stance,re.I))


def context(state):
    actors={state['pc']['id']:state['pc'],**{key:npc for key,npc in state['npcs'].items() if npc['location']==state['pc']['location'] and npc['known']}}
    return {key:{'alive':actor['alive'],'weapons':weapons(state,key),'body':'既定身體的普通動作，不代表超自然力量'} for key,actor in actors.items()}


def validate_harm(state,action,proposal,event,error):
    if set(event)!={'type','actor','target','weapon','condition','fatal','basis'} or type(event.get('fatal')) is not bool:
        raise error('傷勢需要 actor、target、weapon、condition、fatal 與具體依據。')
    for field in ('actor','target','weapon','condition','basis'):
        if not isinstance(event[field],str) or not event[field].strip() or len(event[field])>1200:raise error('傷勢資料不完整。')
    actors={state['pc']['id']:state['pc'],**state['npcs']}
    actor=actors.get(event['actor']);target=actors.get(event['target']);pc=state['pc']
    if not actor or not target or event['actor']==event['target'] or not actor['alive'] or not target['alive']:
        raise error('傷勢的雙方必須是既有、存活且不同的人物。')
    if actor['location']!=pc['location'] or target['location']!=pc['location'] or (event['target']!=pc['id'] and not target['known']):
        raise error('不能傷害不在場或尚未接觸的人物。')
    if event['weapon']!='body' and event['weapon'] not in weapons(state,event['actor']):
        raise error('這次傷害使用了人物尚未持有或未建立的物件。')
    if event['actor']==pc['id']:
        if not attacking(action) or event['target']!=action['target'] or proposal['outcome'] not in {'success','partial'}:
            raise error('不能替玩家執行未宣告的攻擊，或把失敗改成命中。')
    else:
        if event['target']!=pc['id'] or not ((attacking(action) and event['actor']==action['target']) or hostile(actor)):
            raise error('NPC 的傷害需要本回合反擊或先前已建立的敵對情況，不能為普通交談憑空傷人。')
    if event['fatal'] and not re.search(r'死亡|身亡|斷氣|dead|died',event['condition'],re.I):
        raise error('致命結果需要明確記錄死亡狀態，不能把受傷自動當成死亡。')
    if event['fatal'] and re.search(r'未死亡|沒有死亡|未身亡|未斷氣|未死|not dead',event['condition'],re.I):
        raise error('死亡標記與傷勢文字矛盾，不能把未死亡寫成死亡。')
    if not event['fatal'] and re.search(r'已死亡|當場死亡|已身亡|當場身亡|\bdead\b|\bdied\b',event['condition'],re.I) and not re.search(r'未死亡|沒有死亡|not dead',event['condition'],re.I):
        raise error('已死亡的文字需要一致的死亡標記。')


def apply_harm(state,event,revision):
    target=state['pc'] if event['target']==state['pc']['id'] else state['npcs'][event['target']]
    if event['condition'] not in target['conditions']:target['conditions'].append(event['condition'])
    target.setdefault('injuries',[]).append({**{key:event[key] for key in ('actor','weapon','condition','fatal','basis')},'revision':revision})
    if event['target']!=state['pc']['id']:target['encounter']['condition']=event['condition']
    if event['fatal']:target['alive']=False


def consistency(state,action,proposal,error):
    affected=set()
    for event in proposal['events']:
        if event['type']=='harm':
            who=event['target']
            if who in affected:raise error('同一回合的傷勢應合併描述，不能把連刺十次直接當成十次命中。')
            affected.add(who);condition=event['condition']
        elif event['type']=='npc_update' and event.get('field') in {'condition','stance'}:who=event['npc'];condition=event['value']
        else:continue
        if not isinstance(condition,str):continue
        if not has_wound(condition):continue
        player_hit=(event['type']=='harm' and event.get('actor')==state['pc']['id']) or (event['type']=='npc_update' and who==action.get('target') and attacking(action))
        if player_hit and proposal['outcome']=='failure':
            raise error('裁定標成失敗，卻替攻擊目標寫入新傷勢；不能兩者並存。請明確呈現未命中或部分命中的具體交手結果，不要只重述準備動作，也不保證玩家成功。')
        if player_hit and re.search(r'準備|打算|將要|正要',proposal['narration']) and not re.search(r'受傷|刀傷|劍傷|出血|流血|刺中|刺入|劃中|擊中|中刀|斷氣|倒地|死亡|身亡',proposal['narration']):
            raise error('敘事只有準備動作，卻記錄了傷勢。請依現場裁定一次具體交手，不要先寫入尚未呈現的命中。')
        actor=state['pc'] if who==state['pc']['id'] else state['npcs'].get(who)
        if not actor:continue
        names=[part for part in re.split(r'[（()）]',actor['name']) if part]
        for name in names:
            pattern=re.escape(name)+r'(?:[（(][^）)]*[）)])?[，,\s]*(?:仍然|依然|仍|卻|並|也|完全|似乎)?(?:並未|未|沒有)受傷'
            if re.search(pattern,proposal['narration'],re.I):
                raise error('敘事說'+actor['name']+'未受傷，狀態卻記錄了傷勢；這份矛盾回應未生效。')


def ordinary_rationale(state,action,proposal,error):
    if not attacking(action) or proposal['outcome']=='clarify':return
    reason=proposal['reason']
    physical_reason=re.search(r'未命中|格擋|閃避|躲|擋開|距離|護甲|盔甲|鎧甲|防護|護盾|甲殼',reason)
    if not physical_reason and re.search(r'不在.{0,8}(?:已登記|能力範圍)|未(?:登記|學會).{0,10}(?:刺殺|戰鬥|攻擊)|(?:獵刀|普通刀|刀子).{0,8}(?:無法|不能|不可).{0,8}(?:致命|傷害|殺人)',reason):
        raise error('模型把普通持刀動作誤當成未登記能力；普通獵刀可造成傷勢或致命後果，但仍須裁定命中與防禦。')
    # Read the narration, not a reason saying "defended" while the visible
    # story merely repeats drawing weapons and asking what the player intends.
    # Preparation clauses do not count as completed consequences.
    narration=re.sub(r'(?:準備|打算|將要|正要|試圖)[^，,。；;！？\n]*','',proposal['narration'])
    resolved=re.search(r'擋開|擋住|架開|架住|格開|格擋|攔下|攔住|撥開|截住|閃開|閃過|避開|躲開|躲過|偏開|刺空|刺偏|劃空|劃過|擦過|落空|未命中|沒有命中|未能.{0,8}(?:刺|割|砍|碰|接近)|刺(?:中|入|傷|進|穿)|割傷|砍(?:中|傷)|擊中|踢中|打中|受傷|出血|流血|倒地|死亡|身亡|斷氣|夠不到|無法觸及|攻擊範圍外|距離不足|無法靠近|攻擊被.{0,8}(?:阻|擋)|\b(?:blocked|parried|dodged|missed|struck|wounded|injured|interrupted)\b',narration,re.I)
    unfinished=re.search(r'準備|打算|將要|正要|舉起|拔出|拔劍|警告|質問|想做什麼|未發生實際攻擊',proposal['narration']+'\n'+reason)
    if not resolved and unfinished:
        raise error('這次沒有呈現已宣告攻擊的具體結果；拔劍、警告、質問或準備動作不能代替裁定。請當次寫出命中、實際格擋／閃避、落空或具體阻止攻擊的結果，仍不保證命中。')
    for event in proposal['events']:
        if event.get('type')=='npc_update' and event.get('field') in {'condition','stance'} and event.get('npc')==action.get('target') and has_wound(event.get('value','')):
            raise error('這次寫出了攻擊傷勢，但缺少正式 harm 紀錄。請明確記錄已成立傷勢、實際使用的既有武器及是否致命，不要把傷勢塞進參與態度。')


def scene_text(state):
    text=state['locations'][state['pc']['location']]['description'];additions=[]
    for npc in state['npcs'].values():
        changed=npc.get('injuries') or re.search(r'警戒|防衛|交戰|持劍相向|正在攻擊',npc.get('encounter',{}).get('stance',''))
        if not changed:continue
        names=[part for part in re.split(r'[（()）]',npc['name']) if part]
        text=''.join(part for part in re.split(r'(?<=[。！？])|\n+',text) if not any(name in part for name in names))
        if npc['known'] and npc['location']==state['pc']['location']:
            additions.append(npc['name']+'：'+(npc['injuries'][-1]['condition'] if npc.get('injuries') else npc['encounter']['stance']))
    return '\n'.join([text.strip(),*additions]).strip() or '這裡是'+state['locations'][state['pc']['location']]['name']+'。'


def normalize_legacy_wounds(state,action,proposal):
    """Map an already-stated item-attack injury to the typed event, not a new hit."""
    if not isinstance(proposal,dict) or not isinstance(proposal.get('events'),list) or not attacking(action):return proposal
    item=action.get('item')
    if action['kind']!='use_item' or item not in weapons(state,state['pc']['id']) or proposal.get('outcome') not in {'success','partial'}:return proposal
    converted=[]
    for event in proposal['events']:
        value=event.get('value') if isinstance(event,dict) else None
        if isinstance(value,str) and event.get('type')=='npc_update' and event.get('field') in {'condition','stance'} and event.get('npc')==action['target'] and has_wound(value):
            fatal=bool(re.search(r'已死亡|當場死亡|已身亡|當場身亡|(?:中刀|重傷|傷勢).*死亡|^死亡$',value)) and not re.search(r'未死|沒有死亡|可能|差點|瀕臨|恐怕|風險',value)
            converted.append({'type':'harm','actor':state['pc']['id'],'target':event['npc'],'weapon':item,
                'condition':value,'fatal':fatal,'basis':proposal.get('reason','')})
        else:converted.append(event)
    return {**proposal,'events':converted}
