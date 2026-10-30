"""A private story outline and opportunities, subordinate to RPG OS.

The director does not resolve actions, move characters, grant abilities or
repair consequences to fit a plot. Normal play uses the existing GM call.
"""
import copy
from .player_cards import normalize


def context(state):
    story=state.get('story')
    if not story:return None
    plan=story['blueprint'];progress=story['progress']
    chapters={row['id']:row for row in plan['chapters']}
    chapter=chapters[progress['chapter']]
    seen=progress.get('opportunities',{})
    quiet=state['revision']-progress.get('last_offer_revision',-4)>=4
    available=[]
    if quiet and progress.get('status','active')=='active':
        for offer in chapter['opportunities']:
            if offer['id'] in seen or offer['place']!=state['pc']['location']:continue
            carrier=offer['carrier']
            if carrier!='environment':
                npc=state['npcs'].get(carrier)
                if not npc or not npc.get('alive') or npc['location']!=offer['place']:continue
            available.append(copy.deepcopy(offer))
    involved={row['carrier'] for row in available if row['carrier']!='environment'}
    involved.update(chapter['actors'])
    actors={key:{'name':state['npcs'][key]['name'],'alive':state['npcs'][key]['alive'],'location':state['npcs'][key]['location']}
            for key in involved if key in state['npcs']}
    established=[{key:copy.deepcopy(offer[key]) for key in ('id','place','carrier','clue')}
        for row in plan['chapters'] for offer in row['opportunities'] if seen.get(offer['id'])=='presented'][-3:]
    result={'authority':'Planning only. RPG OS v1.01 and actual current reality take priority.',
        'central_conflict':plan['central_conflict'],'ending_conflict':plan['ending_conflict'],
        'fixed_truths':copy.deepcopy(plan['truths']),
        'chapter':{key:copy.deepcopy(chapter[key]) for key in ('id','title','focus','reveals','outcomes')},
        'chapters':[{'id':row['id'],'title':row['title']} for row in plan['chapters']],
        'opportunities':available[:2],'established_threads':established,'actor_reality':actors,'progress':copy.deepcopy(progress)}
    if story.get('generation')=='progressive':
        result['generation']='progressive'
        result['chapter']['detail_status']=chapter.get('detail_status','outline')
        result['chapters']=[{key:row[key] for key in ('id','title','focus')} for row in plan['chapters']]
        result['expansion']={'mode':'on_contact_in_the_same_reply',
            'pending':[row['id'] for row in plan['chapters'] if row.get('detail_status')=='outline'],
            'constraint':'當前章首次使用可先私下準備一小段，不代表玩家已接受、發現或推進；日常閒聊不推進章節。後續細節隨實際探索追加。story_expand 不能重寫真相、地理、人物與後果；新資料先建立後依賴。拒絕線索不可換皮重送。'}
    return result


def apply_expansion(state,after,expansion,narration,revision):
    """Append the contacted chapter's details atomically; never replace canon."""
    if not state.get('story') or not isinstance(expansion,dict):return False
    if set(expansion)-{'chapter','actors','outcomes','opportunities','evidence','planning_truth'}:return False
    evidence=expansion.get('evidence','')
    story=copy.deepcopy(state['story']);plan=story['blueprint']
    chapter=next((row for row in plan['chapters'] if row['id']==expansion.get('chapter')),None)
    if chapter is None:return False
    proof=next((row for row in plan['truths'] if row['id']==expansion.get('planning_truth')),None)
    private_plan=(story.get('generation')=='progressive' and chapter.get('detail_status')=='outline'
        and proof is not None and evidence in (proof['id'],proof['text']))
    if not private_plan and (not isinstance(evidence,str) or len(normalize(evidence))<4 or normalize(evidence) not in normalize(narration)):return False
    # These are references to already persisted records (including records
    # established earlier in this same reply), not permission to teleport them.
    actors=expansion.get('actors',[]);outcomes=expansion.get('outcomes',[]);offers=expansion.get('opportunities',[])
    if not all(isinstance(items,list) for items in (actors,outcomes,offers)):return False
    if len(actors)>4 or len(outcomes)>4 or len(offers)>3:return False
    if any(not isinstance(key,str) or key not in after['npcs'] for key in actors):return False
    if any(not isinstance(value,str) or not 1<=len(value)<=240 for value in outcomes):return False
    ids={item['id'] for row in plan['chapters'] for item in row['opportunities']}
    added=[]
    for offer in offers:
        if not isinstance(offer,dict) or set(offer)!={'id','place','carrier','clue','basis'}:return False
        if any(not isinstance(value,str) or not 1<=len(value)<=500 for value in offer.values()):return False
        if offer['id'] in ids:
            if private_plan and any(offer==old for old in chapter['opportunities']):continue
            return False
        if offer['place'] not in after['locations']:return False
        carrier=offer['carrier']
        if carrier!='environment':
            npc=after['npcs'].get(carrier)
            if not npc or not npc.get('alive') or npc['location']!=offer['place']:return False
            # A newly established lead cannot resurrect an old rejected/lost
            # clue under a different ID. Exact persisted wording is comparable.
        if any(normalize(old['clue'])==normalize(offer['clue']) for row in plan['chapters'] for old in row['opportunities']):return False
        ids.add(offer['id']);added.append(copy.deepcopy(offer))
    if len(chapter['opportunities'])+len(added)>12:return False
    if not actors and not outcomes and not added:return False
    chapter['actors']=list(dict.fromkeys([*chapter['actors'],*actors]))
    chapter['outcomes']=list(dict.fromkeys([*chapter['outcomes'],*outcomes]))[:8]
    chapter['opportunities'].extend(added)
    chapter['detail_status']='developing';chapter['expanded_revision']=revision
    from .engine import RuleError
    try:validate(story,after,RuleError)
    except (RuleError,TypeError,KeyError):return False
    after['story']=story
    return True


def apply_update(state, after, update, narration, revision):
    """Store supported progress only; malformed optional notes never block play."""
    if not state.get('story') or not isinstance(update,dict):return
    evidence=update.get('evidence','')
    if not isinstance(evidence,str) or len(normalize(evidence))<4 or normalize(evidence) not in normalize(narration):return
    story=copy.deepcopy(after.get('story',state['story']));plan=story['blueprint'];progress=story['progress']
    chapters={row['id'] for row in plan['chapters']}
    truths={row['id'] for row in plan['truths']}
    offers={offer['id'] for row in plan['chapters'] for offer in row['opportunities']}
    changed=False
    if update.get('chapter') in chapters and update['chapter']!=progress['chapter']:
        progress['chapter']=update['chapter'];changed=True
    for key,status in update.get('opportunities',{}).items() if isinstance(update.get('opportunities'),dict) else []:
        if key not in offers or status not in ('presented','followed','declined','lost'):continue
        old=progress['opportunities'].get(key)
        if old==status or (old in ('followed','declined','lost') and status=='presented'):continue
        progress['opportunities'][key]=status;changed=True
        if status=='presented':progress['last_offer_revision']=revision
    for key in update.get('revealed',[]) if isinstance(update.get('revealed'),list) else []:
        if key in truths and key not in progress['revealed']:
            progress['revealed'].append(key);changed=True
    if update.get('status') in ('active','paused','resolved','abandoned') and update['status']!=progress['status']:
        progress['status']=update['status'];changed=True
    summary=update.get('summary')
    if changed:
        progress['recent'].append({'revision':revision,'summary':summary[:240] if isinstance(summary,str) else evidence[:240]})
        progress['recent']=progress['recent'][-5:]
        after['story']=story


def validate(story,state,error):
    if not isinstance(story,dict) or story.get('version')!=1:raise error('故事大綱格式不正確。')
    plan=story.get('blueprint');progress=story.get('progress')
    if not isinstance(plan,dict) or not isinstance(progress,dict):raise error('故事大綱或進度不完整。')
    if not all(isinstance(plan.get(key),list) for key in ('truths','chapters')):raise error('故事章節不完整。')
    if not all(isinstance(plan.get(key),str) for key in ('central_conflict','ending_conflict')):raise error('故事核心衝突不完整。')
    if not plan['chapters'] or len(plan['chapters'])>8:raise error('故事需要有界的章節大綱。')
    truths=set();chapters=set();offers=set()
    for truth in plan['truths']:
        if not isinstance(truth,dict) or not isinstance(truth.get('id'),str) or not isinstance(truth.get('text'),str) or truth['id'] in truths:raise error('故事真相識別重複或不完整。')
        truths.add(truth['id'])
    for chapter in plan['chapters']:
        if not isinstance(chapter,dict) or not isinstance(chapter.get('id'),str) or chapter['id'] in chapters:raise error('故事章節識別不完整。')
        chapters.add(chapter['id'])
        if chapter.get('detail_status','ready') not in ('outline','developing','ready'):raise error('章節展開狀態不正確。')
        if not all(isinstance(chapter.get(key),str) for key in ('title','focus')) or not all(isinstance(chapter.get(key),list) for key in ('reveals','actors','outcomes','opportunities')):raise error('故事章節缺少方向或途徑。')
        if set(chapter['reveals'])-truths or set(chapter['actors'])-set(state['npcs']):raise error('章節引用未建立的人物或真相。')
        if any(not isinstance(value,str) for value in chapter['outcomes']):raise error('章節可能結果格式不正確。')
        for offer in chapter['opportunities']:
            if not isinstance(offer,dict) or not all(isinstance(offer.get(key),str) for key in ('id','place','carrier','clue','basis')) or offer['id'] in offers:raise error('故事機會缺少因果或識別。')
            if offer['place'] not in state['locations'] or offer['carrier'] not in {'environment',*state['npcs']}:raise error('故事機會引用未建立的人物或地點。')
            offers.add(offer['id'])
    if progress.get('chapter') not in chapters or progress.get('status') not in ('active','paused','resolved','abandoned'):raise error('故事進度引用不存在的章節。')
    if not isinstance(progress.get('revealed'),list) or set(progress['revealed'])-truths:raise error('故事揭露紀錄不正確。')
    if not isinstance(progress.get('opportunities'),dict) or set(progress['opportunities'])-offers:raise error('故事機會紀錄不正確。')
    if any(value not in ('presented','followed','declined','lost') for value in progress['opportunities'].values()):raise error('故事機會狀態不正確。')
    if not isinstance(progress.get('recent'),list) or type(progress.get('last_offer_revision')) is not int:raise error('故事進度來源不完整。')
