"""Establish a world, then a private dramatic outline before the opening."""
import copy
import json
from .engine import RuleError
from .worldgen import generate_plan,validate_opening,_text
from .world_schema import obj,text,texts,rows,BILINGUAL_NAME
from .model import _complete
from .rulebook import verified_sources,section
from .canon import establish
from .names import has_english
from .progress import stage
from .story_director import validate


def bounded(size):return {'type':'string','minLength':1,'maxLength':size}
def array(items,minimum=0,maximum=8):return {'type':'array','items':items,'minItems':minimum,'maxItems':maximum}
POWER=obj({key:bounded(200) for key in ('name','effect','limits')})
CAST=obj({**{key:bounded(240) for key in ('id','name','species','role','description','personality','values','concern','boundary','levers','activity','location')},'powers':array(POWER,0,2)})
SITE=obj({key:bounded(300) for key in ('id','name','description','connects_to','route_basis')})
CAST['properties']['name']=dict(BILINGUAL_NAME)
SITE['properties']['name']=dict(BILINGUAL_NAME)
OFFER=obj({key:bounded(220) for key in ('id','place','carrier','clue','basis')})
CHAPTER=obj({'id':bounded(60),'title':bounded(80),'focus':bounded(240),'reveals':array(bounded(60),1,3),
    'actors':array(bounded(80),0,3),'outcomes':array(bounded(160),2,4),'opportunities':array(OFFER,2,3)})
STORY_SCHEMA=obj({'central_conflict':bounded(400),'ending_conflict':bounded(400),
    'truths':array(obj({'id':bounded(60),'text':bounded(300)}),3,5),
    'sites':array(SITE,2,2),'cast':array(CAST,2,2),'chapters':array(CHAPTER,3,5),'opening':bounded(1800)})


def story_schema(seed):
    schema=copy.deepcopy(STORY_SCHEMA)
    places=[*seed['locations'],'story_place_1','story_place_2']
    actors=[*seed['npcs'],'story_actor_1','story_actor_2']
    def enum(values):return {'type':'string','enum':list(values)}
    site=schema['properties']['sites']['items']['properties']
    site['id']=enum(['story_place_1','story_place_2']);site['connects_to']=enum(seed['locations'])
    cast=schema['properties']['cast']['items']['properties']
    cast['id']=enum(['story_actor_1','story_actor_2']);cast['location']=enum(['story_place_1','story_place_2'])
    truth=schema['properties']['truths'];truth['minItems']=3;truth['maxItems']=3
    truth['items']['properties']['id']=enum(['truth_1','truth_2','truth_3'])
    chapter=schema['properties']['chapters']['items']['properties']
    chapter['id']=enum(['chapter_'+str(i) for i in range(1,6)])
    chapter['reveals']['items']=enum(['truth_1','truth_2','truth_3']);chapter['actors']['items']=enum(actors)
    offer=chapter['opportunities']['items']['properties']
    offer['place']=enum(places);offer['carrier']=enum(['environment',*actors])
    return schema

SYSTEM='''你是 Taleoria 的故事設計者，服從提供的 RPG OS v1.01。這是在開場前建立世界基礎，不是替玩家遊玩。
依已建立的世界、主角與玩家偏好，預寫一段有伏筆、推進、代價與終局衝突的故事核心。題材可以是奇幻、懸疑或日常；終局不必是戰鬥，更不保證主角勝利或愛情。
固定三至五項具體真相，三至五章的方向、重要揭露與不同可能結果；不能預定玩家的行動、台詞、感情、陣營、勝敗或必經順序。玩家可以停留生活、繞路、拒絕、失去線索、投靠另一方或提早解決衝突。重要人物死亡與其他後果不能為原稿取消。
新增二至三個固定地點、兩名重要成年人物，與原本人物及起點一起組成核心。所有 name 使用中文（English Name）。原有世界、地點、人物和玩家能力保持原設定；不能為主線賦予玩家印記、血統、神力或新能力。新人物先建立個性、牽掛、顧慮、界線、活動及實際住處；能力需要具體效果與限制，非超自然世界用空 powers。
新地點 id 使用 story_place_1 等，connects_to 只能引用資料中的地點 ID 或其他新地點 ID，route_basis 說明實際通路；不能移動已建立的地點。新人物 id 使用 story_actor_1、story_actor_2，location 引用已建立或這次新增的地點 ID；role 是真實身分，description 只寫可見外觀。
每章提供至少兩個來自不同地點或不同人物的機會，而不是重送同一邀請。機會 place 引用實際地點 ID，carrier 引用人物 ID 或 environment；clue 是該處可能察覺的具體線索，basis 說明它為何在那裡、如何連向固定真相。第一章至少有一個機會位於起點或原有附近地點。不能讓遠處的人憑空出現。人物有自己的生活，不是每人都催玩家接主線。
truths 的 id 使用 truth_1 等，章節 id 使用 chapter_1 等，reveals 引用真相 ID，actors 引用核心人物 ID（原本在場者是 guide）。opportunities 的 id 全故事唯一。outcomes 是開放的可能，不是要達成的任務清單。
opening 用一至兩段自然繁體中文，只描寫已建立起點的景物、原本在場人物的活動與一句自然台詞。可以有細微伏筆，不揭露秘密，不替玩家做任何選擇。不要把新遠處人物放到開場，不施放未建立力量。
預設先寫三章，各欄位用一個短句：個性、顧慮、線索與因果各約二十至四十字，opening 合計約一百二十字。內容具體而精簡，不長篇重述。只回傳指定 JSON。'''


def build_story(candidate,raw):
    """Materialize fixed anchors first; keep flexible opportunities private."""
    required={'central_conflict','ending_conflict','truths','sites','cast','chapters','opening'}
    if not isinstance(raw,dict) or set(raw)!=required:raise RuleError('故事核心草案不完整，尚未建立世界。')
    candidate=copy.deepcopy(candidate);state=candidate['seed'];prefs=candidate['preferences']
    if not isinstance(raw['truths'],list) or not 3<=len(raw['truths'])<=5 or not isinstance(raw['chapters'],list) or not 3<=len(raw['chapters'])<=5:raise RuleError('故事需要三至五項真相與三至五章方向。')
    for key in ('central_conflict','ending_conflict'):_text(raw[key],key,2400)
    if not isinstance(raw['sites'],list) or not 2<=len(raw['sites'])<=3:raise RuleError('故事地點草案不完整。')
    if not isinstance(raw['cast'],list) or len(raw['cast'])!=2:raise RuleError('故事核心人物草案不完整。')
    source='RPG OS v1.01 開場前建立的故事核心；機會可變，世界事實與人物後果不為主線重寫'
    new_places={}
    for place in raw['sites']:
        if not isinstance(place,dict) or set(place)!=set(SITE['properties']):raise RuleError('故事地點缺少通路來源。')
        for value in place.values():_text(value,'故事地點',800)
        key=place['id']
        if key in state['locations'] or key in new_places:raise RuleError('故事地點識別重複。')
        if not has_english(place['name']):raise RuleError('故事地點需要中英文名稱。')
        new_places[key]={'name':place['name'],'description':place['description'],'exits':{},'source':source}
    state['locations'].update(new_places)
    for place in raw['sites']:
        key,target=place['id'],place['connects_to']
        if target not in state['locations'] or target==key:raise RuleError('故事通路引用不存在的地點。')
        for a,b in ((key,target),(target,key)):
            state['locations'][a]['exits'][b]={'known':False,'clear':True,'basis':place['route_basis']}
    reachable={state['pc']['location']};queue=list(reachable)
    while queue:
        for key in state['locations'][queue.pop(0)]['exits']:
            if key not in reachable:reachable.add(key);queue.append(key)
    if set(new_places)-reachable:raise RuleError('故事地點需要有實際可連接的通路。')
    for person in raw['cast']:
        if not isinstance(person,dict) or set(person)!=set(CAST['properties']):raise RuleError('故事人物缺少個人基礎。')
        for key in set(person)-{'powers'}:_text(person[key],'故事人物',800)
        key=person['id'];place=person['location']
        if key in state['npcs'] or key==state['pc']['id'] or place not in state['locations']:raise RuleError('故事人物識別或位置不正確。')
        if not has_english(person['name']):raise RuleError('故事人物需要中英文名稱。')
        if not isinstance(person['powers'],list) or len(person['powers'])>2:raise RuleError('故事人物能力資料不正確。')
        if prefs['magic']=='沒有超自然能力' and person['powers']:raise RuleError('這個世界沒有設定超自然能力。')
        state['npcs'][key]={'id':key,'name':person['name'],'location':place,'known':False,'alive':True,
            'description':person['description'],'anchor':{k:person[k] for k in ('values','concern','boundary','levers')},
            'encounter':{'condition':person['activity'],'priorities':person['concern'],
                         'appraisal':'尚未接觸主角，依實際感知形成評價','attraction':'尚未建立對主角的吸引或排斥','stance':'尚未接觸，依個性與當下情境反應'},
            'knowledge':[person['role'],person['activity']],'conditions':[],
            'inner_life':{'personality':{'description':person['personality'],'basis':source,'established_revision':0},
                          'limits':[],'current_emotions':[],'relationships':{},'memories':[],'personality_history':[]}}
        establish(state,{'kind':'identity','actor':key,'species':person['species'],'role':person['role'],
            'forms':{'base':person['species']+'的已建立身體'},'current_form':'base'},source,0,RuleError)
        for index,power in enumerate(person['powers']):
            if not isinstance(power,dict) or set(power)!=set(POWER['properties']):raise RuleError('故事人物能力缺少效果與限制。')
            for value in power.values():_text(value,'故事能力',800)
            establish(state,{'kind':'power','id':key+'_power_'+str(index+1),'actor':key,'name':power['name'],
                'effect':power['effect']+'；限制：'+power['limits'],'requires_flags':[],'result_form':None},source,0,RuleError)
    blueprint={key:copy.deepcopy(raw[key]) for key in ('central_conflict','ending_conflict','truths','chapters')}
    state['story']={'version':1,'authority':'RPG OS v1.01','blueprint':blueprint,
        'progress':{'chapter':raw['chapters'][0]['id'] if raw.get('chapters') else '', 'status':'active',
                    'revealed':[],'opportunities':{},'last_offer_revision':-4,'recent':[]}}
    validate(state['story'],state,RuleError)
    for chapter in blueprint['chapters']:
        for offer in chapter['opportunities']:
            carrier=state['npcs'].get(offer['carrier'])
            if carrier and offer['clue'] not in carrier['knowledge']:carrier['knowledge'].append(offer['clue'])
    original_opening=candidate['plan']['opening']
    candidate['plan']['opening']=raw['opening']
    try:validate_opening(candidate['plan'])
    except (RuleError,TypeError,KeyError):
        # Reuse the already-established, validated opening instead of throwing
        # away an entire outline or generating another version of reality.
        candidate['plan']['opening']=original_opening
        validate_opening(candidate['plan'])
    candidate.update(source_mode='rpg_os_director',audit=None)
    return candidate


def generate_world(raw,model_url):
    candidate=generate_plan(raw,model_url)
    sources=verified_sources()
    rules=section(sources['OS_LAW.md'],'## Establish',1800)+'\n\n'+sources['ENGINE_freeform.md']
    # A compact seed projection keeps creation within a local model's context.
    seed=candidate['seed']
    planning={'preferences':candidate['preferences'],'world':candidate['plan']['background'],
        'world_rules':candidate['plan']['rules'],'player':candidate['plan']['player'],
        'places':seed['locations'],'guide':candidate['plan']['npc']}
    with stage('預寫故事核心與章節'):
        outline=_complete([{'role':'system','content':'RPG OS v1.01 原文依據：\n'+rules+'\n\n'+SYSTEM},
            {'role':'user','content':json.dumps(planning,ensure_ascii=False)}],model_url,3600,.55,timeout=300,response_schema=story_schema(seed))
    # Compatibility with adapters that ignore a name pattern: repair names only,
    # never regenerate fictional facts or the player's decisions.
    holders={row.get('id'):row for field in ('sites','cast') for row in outline.get(field,[]) if isinstance(row,dict)} if isinstance(outline,dict) else {}
    missing={key:row['name'] for key,row in holders.items() if isinstance(key,str) and isinstance(row.get('name'),str) and not has_english(row['name'])}
    if missing:
        with stage('補齊故事人物與地點英文名'):
            names=_complete([{'role':'system','content':'只翻譯或音譯給定名稱為簡短英文名。只回傳相同鍵的 JSON，值用英文字母、空格、連字號或撇號。不新增背景。'},
                {'role':'user','content':json.dumps(missing,ensure_ascii=False)}],model_url,300,.2,response_schema=obj({key:text() for key in missing}))
        if not isinstance(names,dict) or set(names)!=set(missing):raise RuleError('故事名稱整理未完成，尚未建立世界。')
        import re
        for key,value in names.items():
            if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z][A-Za-z '\-]{0,80}",value):raise RuleError('故事英文名格式不完整。')
            holders[key]['name']=missing[key]+'（'+value+'）'
    with stage('建立固定人物、地點與故事進度'):
        return build_story(candidate,outline)
