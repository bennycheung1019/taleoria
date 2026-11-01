"""Select a working scene from durable world records, without deleting canon.

Ranking is retrieval only: it does not classify actions, resolve outcomes, move
people, decide what someone knows, or author fictional summaries.
"""
import copy
import json
import re
from .names import aliases
from .references import mentions,name_options


def words(text):
    result=set(re.findall(r'[a-z]{3,}',text.lower()))
    for run in re.findall(r'[\u4e00-\u9fff]{2,}',text):
        result.update(run[i:i+2] for i in range(len(run)-1))
    return result-{'一個','這個','那個','的人','甚麼','什麼','他們','她們','我們'}


def score(value,query):
    text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
    return sum(word in text.lower() for word in query)


def recall(items,text,maximum=6):
    if not isinstance(items,list):return []
    query=words(text)
    recent=list(range(max(0,len(items)-maximum//2),len(items)))
    ranked=sorted(range(len(items)),key=lambda i:(score(items[i],query),i),reverse=True)
    chosen=set(recent)
    for index in ranked:
        if len(chosen)>=maximum:break
        chosen.add(index)
    return [copy.deepcopy(items[i]) for i in sorted(chosen)]


def project(state,text,full_limit=4,index_limit=24):
    here=state['pc']['location'];registry=aliases(state);query=words(text)
    local={key:npc for key,npc in state['npcs'].items() if npc['location']==here}
    explicit={key for key,npc in local.items() if mentions(npc,text,registry)}
    memory=state.get('scene_memory',{})
    focus=memory.get('focus',{}).get(here,[]) if isinstance(memory,dict) else []
    interlocutor=memory.get('interlocutor',{}).get(here) if isinstance(memory,dict) else None
    contacts=memory.get('contacts',{}) if isinstance(memory,dict) else {}
    def rank(key):
        npc=local[key]
        return (key in explicit,key==interlocutor,score(npc.get('description',''),query),key in focus,
                contacts.get(key,0),npc.get('detail_level')!='incidental')
    ordered=sorted(local,key=rank,reverse=True)
    selected=set(ordered[:full_limit])|explicit
    npcs={key:copy.deepcopy(local[key]) for key in ordered if key in selected}
    for npc in npcs.values():
        life=npc.get('inner_life',{})
        if isinstance(life,dict) and isinstance(life.get('memories'),list):
            life['memories']=recall(life['memories'],text)
    indexed=[key for key in ordered if key not in selected][:index_limit]
    index={key:{'name':local[key]['name'],'description':local[key]['description'][:100],
                'alive':local[key]['alive'],'detail_level':local[key].get('detail_level','established')}
           for key in indexed}
    near={here,*state['locations'][here]['exits']}
    named={key for key,place in state['locations'].items()
           if any(name.casefold() in text.casefold() for name in name_options(state,key,place))}
    places={key:copy.deepcopy(state['locations'][key]) for key in near|named}
    return {'npcs':npcs,'scene_people':index,'locations':places,
        'scene_scope':{'present_count':len(local),'detail_ids':list(npcs),
            'other_people_not_loaded':max(0,len(local)-len(npcs)-len(index)),
            'storage':'其餘人物與遠處地點仍完整存檔；未載入不是不存在。按名稱、外觀與最近接觸回取；索引人物沿用原 ID，不能重新生成。人群背景不逐人建檔，實際互動才建立。'}}


def remember(state,after,changes,narration,revision):
    """Persist only indices and evidenced notes; full histories remain intact."""
    here=after['pc']['location'];registry=aliases(after)
    explicit=changes.get('scene_focus',[])
    if not isinstance(explicit,list):explicit=[]
    keys=[*explicit,*list(changes.get('npcs',{}))] if isinstance(changes.get('npcs',{}),dict) else explicit
    keys.extend(key for key,npc in after['npcs'].items() if mentions(npc,narration,registry))
    keys=list(dict.fromkeys(key for key in keys if isinstance(key,str) and key in after['npcs'] and after['npcs'][key]['location']==here))
    memory=copy.deepcopy(state.get('scene_memory',{'version':1,'focus':{},'contacts':{}}))
    memory.setdefault('focus',{});memory.setdefault('contacts',{})
    memory.setdefault('interlocutor',{})
    if keys:memory['focus'][here]=keys[:4]
    for key in keys:memory['contacts'][key]=revision
    focused=[key for key in explicit if key in after['npcs'] and
             after['npcs'][key]['location']==here]
    if focused:
        memory['interlocutor'][here]=focused[-1]
    elif len(keys)==1 and '「' in narration and '」' in narration:
        memory['interlocutor'][here]=keys[0]
    after['scene_memory']=memory
    return keys
