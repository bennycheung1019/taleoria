"""Portable JSON game files. Only data is imported, never SQL or executable code."""
import copy
import hashlib
import hmac
import json
from datetime import datetime, timezone
from .engine import canonical, RuleError

FORMAT = 'kobold-rpg-save'
MAX_BYTES = 16 * 1024 * 1024
JOURNAL_KEYS = {'revision', 'request_id', 'body', 'before_state', 'after_state', 'previous_hash', 'hash'}


def validate_state(state):
    required = {'campaign_id','revision','contract','pc','abilities','locations','npcs','facts','open_matters'}
    if not isinstance(state, dict) or not required <= set(state):
        raise RuleError('存檔缺少完整的世界資料。')
    if not isinstance(state['campaign_id'], str) or type(state['revision']) is not int or state['revision'] < 0:
        raise RuleError('存檔的世界識別或進度不正確。')
    if not isinstance(state['contract'], dict) or not isinstance(state['abilities'], dict):
        raise RuleError('存檔的遊玩約定或能力資料不正確。')
    if not isinstance(state['contract'].get('canon_policy'),str) and 'canon' in state:
        raise RuleError('存檔缺少身分與能力的世界約定。')
    if not isinstance(state['open_matters'],list) or any(not isinstance(v,str) for v in state['open_matters']):
        raise RuleError('存檔待辦事項格式不正確。')
    pc = state['pc']; places = state['locations']
    if not isinstance(pc, dict) or not {'id','name','alive','location','capabilities','spells','inventory','resources','conditions','goal'} <= set(pc):
        raise RuleError('存檔缺少完整的角色資料。')
    if not isinstance(pc['id'], str) or not isinstance(pc['name'], str) or type(pc['alive']) is not bool:
        raise RuleError('存檔角色資料不正確。')
    if not isinstance(places, dict) or not places or not isinstance(pc['location'], str) or pc['location'] not in places:
        raise RuleError('存檔角色所在位置不存在。')
    for field in ('capabilities','spells','conditions'):
        if not isinstance(pc[field], list) or any(not isinstance(v,str) for v in pc[field]):
            raise RuleError('存檔能力或狀況格式不正確。')
    for field in ('inventory','resources'):
        if not isinstance(pc[field], dict) or any(not isinstance(k,str) or type(v) is not int or v < 0 for k,v in pc[field].items()):
            raise RuleError('存檔物品或資源格式不正確。')
    if any(key not in state['abilities'] for key in pc['spells']):
        raise RuleError('存檔有找不到來源的能力。')
    for place in places.values():
        if not isinstance(place, dict) or not {'name','description','exits'} <= set(place) or not isinstance(place['exits'],dict):
            raise RuleError('存檔地圖格式不正確。')
        if not isinstance(place['name'],str) or not isinstance(place['description'],str):
            raise RuleError('存檔地點描述不正確。')
        for target,route in place['exits'].items():
            if target not in places or not isinstance(route,dict) or type(route.get('known')) is not bool:
                raise RuleError('存檔包含不存在的通路。')
    if not isinstance(state['npcs'],dict) or not isinstance(state['facts'],list) or not isinstance(state['open_matters'],list):
        raise RuleError('存檔人物或見聞格式不正確。')
    for key,npc in state['npcs'].items():
        fields={'id','name','description','location','known','alive','anchor','encounter','knowledge','conditions'}
        if not isinstance(npc,dict) or not fields <= set(npc) or npc['id'] != key or npc['location'] not in places:
            raise RuleError('存檔人物資料不完整。')
        if not isinstance(npc['anchor'],dict) or not isinstance(npc['encounter'],dict) or type(npc['known']) is not bool or type(npc['alive']) is not bool:
            raise RuleError('存檔人物基礎不正確。')
        if any(not isinstance(npc[k],str) for k in ('id','name','description','location')) or any(not isinstance(npc[k],list) for k in ('knowledge','conditions')):
            raise RuleError('存檔人物描述格式不正確。')
        if 'dialogue' in npc:
            from .dialogue import validate_record
            validate_record(npc['dialogue'],state['revision'],RuleError)
    for fact in state['facts']:
        if not isinstance(fact,dict) or fact.get('visibility') not in {'public','private'} or not isinstance(fact.get('text'),str):
            raise RuleError('存檔的公開與私人資料不正確。')
    for actor in [pc,*state['npcs'].values()]:
        injuries=actor.get('injuries',[])
        if not isinstance(injuries,list):raise RuleError('存檔傷勢紀錄格式不正確。')
        for injury in injuries:
            keys={'actor','weapon','condition','fatal','basis','revision'}
            if not isinstance(injury,dict) or set(injury)!=keys or type(injury['fatal']) is not bool or type(injury['revision']) is not int or any(not isinstance(injury[key],str) for key in ('actor','weapon','condition','basis')):
                raise RuleError('存檔傷勢紀錄不完整。')
    if 'canon' in state:
        canon=state['canon']
        if not isinstance(canon,dict) or not {'actors','powers','flags','uses'} <= set(canon) or not isinstance(canon['actors'],dict) or not isinstance(canon['powers'],dict):
            raise RuleError('存檔缺少身分與能力登記。')
        if ({pc['id']} | set(state['npcs'])) - set(canon['actors']):
            raise RuleError('存檔有尚未建立身分的人物。')
        if not isinstance(canon['flags'],dict) or not isinstance(canon['uses'],list):
            raise RuleError('存檔能力狀態格式不正確。')
        for owner,identity in canon['actors'].items():
            if not isinstance(identity,dict) or not {'species','role','forms','current_form','powers','source','established_revision'} <= set(identity):
                raise RuleError('存檔身分格式不完整。')
            if not isinstance(identity['forms'],dict) or identity['current_form'] not in identity['forms'] or not isinstance(identity['powers'],list):
                raise RuleError('存檔形態或能力不正確。')
            for power in identity['powers']:
                if power not in canon['powers'] or canon['powers'][power].get('actor') != owner:
                    raise RuleError('存檔能力擁有人不一致。')
    from .player_cards import validate as validate_player_card
    if 'story' in state:
        from .story_director import validate as validate_story
        validate_story(state['story'],state,RuleError)
    if 'scene_memory' in state:
        memory=state['scene_memory']
        if not isinstance(memory,dict) or memory.get('version')!=1 or not isinstance(memory.get('focus'),dict) or not isinstance(memory.get('contacts'),dict):
            raise RuleError('場景記憶索引格式不正確。')
        for place,keys in memory['focus'].items():
            if place not in places or not isinstance(keys,list) or any(not isinstance(key,str) or key not in state['npcs'] for key in keys):raise RuleError('場景人物索引不正確。')
        if any(key not in state['npcs'] or type(value) is not int or not 0<=value<=state['revision'] for key,value in memory['contacts'].items()):raise RuleError('人物接觸紀錄不正確。')
    for npc in state['npcs'].values():
        if 'player_view' in npc:validate_player_card(npc['player_view'],state['revision'],RuleError)
    notes=state.get('people_notes',{})
    if not isinstance(notes,dict):
        raise RuleError('存檔人物見聞格式不正確。')
    for npc_id,entries in notes.items():
        if npc_id not in state['npcs'] or not isinstance(entries,list):
            raise RuleError('存檔人物見聞的對象不存在。')
        for note in entries:
            if not isinstance(note,dict) or note.get('kind') not in {'said','observed'} or not isinstance(note.get('quote'),str) or type(note.get('revision')) is not int:
                raise RuleError('存檔人物見聞缺少來源。')


def export_file(engine):
    from .turn_updates import latest
    if latest(engine):raise RuleError('人物紀錄整理完成後才能下載完整存檔。')
    with engine.connect() as db:
        db.execute('BEGIN')
        if db.execute("SELECT 1 FROM turn_updates WHERE status!='done' LIMIT 1").fetchone():
            raise RuleError('人物紀錄整理完成後才能下載完整存檔。')
        state=json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
        journal=[dict(row) for row in db.execute('SELECT * FROM journal ORDER BY revision')]
    payload={'format':FORMAT,'version':1,'created_at':datetime.now(timezone.utc).isoformat(),
             'state':state,'journal':journal}
    payload['checksum']=hashlib.sha256(canonical(payload).encode()).hexdigest()
    validate_file(payload)
    return payload


def validate_file(payload):
    if not isinstance(payload,dict) or set(payload) != {'format','version','created_at','state','journal','checksum'} or payload.get('format') != FORMAT or payload.get('version') != 1:
        raise RuleError('這不是完整的 RPG 存檔。請選擇新的 .rpgsave 遊戲檔，舊版閱讀副本不能完整載入。')
    if len(canonical(payload).encode()) > MAX_BYTES:
        raise RuleError('存檔超過目前支援的 16 MB。')
    checksum=payload['checksum']
    expected=hashlib.sha256(canonical({k:v for k,v in payload.items() if k!='checksum'}).encode()).hexdigest()
    if not isinstance(checksum,str) or not hmac.compare_digest(checksum,expected):
        raise RuleError('存檔內容不完整或已損壞；目前冒險沒有改動。')
    validate_state(payload['state'])
    journal=payload['journal']
    if not isinstance(journal,list) or len(journal)>20000:
        raise RuleError('存檔事件紀錄不正確。')
    previous='0'*64;last_after=None;requests=set()
    for revision,row in enumerate(journal,1):
        if not isinstance(row,dict) or set(row)!=JOURNAL_KEYS or row['revision']!=revision:
            raise RuleError('存檔事件順序不完整。')
        if any(not isinstance(row[k],str) for k in JOURNAL_KEYS-{'revision'}):
            raise RuleError('存檔事件格式不正確。')
        if row['request_id'] in requests:
            raise RuleError('存檔事件重複。')
        requests.add(row['request_id'])
        calculated=hashlib.sha256((previous+row['body']+row['before_state']+row['after_state']).encode()).hexdigest()
        if row['previous_hash']!=previous or row['hash']!=calculated or (last_after is not None and row['before_state']!=last_after):
            raise RuleError('存檔的事件與世界狀態不連續。')
        try:
            before=json.loads(row['before_state']);after=json.loads(row['after_state']);body=json.loads(row['body'])
            validate_state(before);validate_state(after)
            if before['revision']!=revision-1 or after['revision']!=revision or not isinstance(body,dict) or not isinstance(body.get('narration'),str):
                raise RuleError('存檔事件版本或敘事不正確。')
        except (ValueError,TypeError,KeyError) as exc:
            raise RuleError('存檔事件資料無法讀取。') from exc
        previous=row['hash'];last_after=row['after_state']
    if payload['state']['revision']!=len(journal) or (last_after is not None and last_after!=canonical(payload['state'])):
        raise RuleError('存檔進度與最後事件不一致。')
    return copy.deepcopy(payload)
