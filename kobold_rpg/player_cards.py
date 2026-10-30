"""Player-facing notes, kept separate from an NPC's private inner life.

Optional display annotations never approve or reject a player's action/story.
Only notes supported by a delivered passage and a perceived encounter are saved.
"""
import copy
import re
import unicodedata


def normalize(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))


def present(state, key):
    npc=state.get('npcs',{}).get(key,{})
    return npc.get('known') and npc.get('location')==state['pc']['location']


def apply_updates(before, after, patches, narration, revision):
    visible=normalize(narration) if isinstance(narration,str) else ''
    for key,patch in patches.items():
        if key not in after['npcs'] or not isinstance(patch,dict):continue
        if not (present(before,key) or present(after,key)):continue
        current=copy.deepcopy(before.get('npcs',{}).get(key,{}).get('player_view',{}))
        if not isinstance(current,dict):current={}
        def entry(value, fact=False):
            if not isinstance(value,dict):return None
            text=value.get('text');evidence=value.get('evidence')
            if not isinstance(text,str) or not 1<=len(text.strip())<=240:return None
            if not isinstance(evidence,str) or not 4<=len(normalize(evidence))<=240:return None
            if normalize(evidence) not in visible:return None
            if fact and value.get('kind') not in ('said','observed'):return None
            result={'text':text.strip(),'evidence':evidence.strip()}
            if fact:result['kind']=value['kind']
            return result
        facts=patch.get('facts',{})
        if isinstance(facts,dict):
            for topic,value in list(facts.items())[:12]:
                if not isinstance(topic,str) or not 1<=len(topic)<=80:continue
                saved=entry(value,True)
                if saved is None:continue
                known=current.setdefault('facts',{})
                old=known.get(topic,{})
                if all(old.get(field)==saved[field] for field in ('text','kind')):continue
                known[topic]={**saved,'revision':revision}
        for field in ('relationship','condition'):
            saved=entry(patch.get(field))
            if saved is not None and current.get(field,{}).get('text')!=saved['text']:
                current[field]={**saved,'revision':revision}
        if current:after['npcs'][key]['player_view']=current


def validate(value, revision, error):
    if not isinstance(value,dict):raise error('存檔人物公開資料格式不正確。')
    facts=value.get('facts',{})
    if not isinstance(facts,dict):raise error('存檔人物已知資訊格式不正確。')
    entries=[(item,True) for item in facts.values()]
    entries.extend((value[field],False) for field in ('relationship','condition') if field in value)
    for item,fact in entries:
        if (not isinstance(item,dict) or not isinstance(item.get('text'),str)
                or not isinstance(item.get('evidence'),str)
                or type(item.get('revision')) is not int or not 0<=item['revision']<=revision
                or (fact and item.get('kind') not in ('said','observed'))):
            raise error('存檔人物公開資料缺少內容或來源。')
