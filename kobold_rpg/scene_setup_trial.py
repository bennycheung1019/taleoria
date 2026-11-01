"""Focused, sourced scene-object extraction after a world draft exists."""
import copy
import json
import re

from .context_budget import budget,count
from .engine import RuleError
from .model import _complete,parse_proposal


OBJECT_SCHEMA={'type':'object','properties':{
    'name_quote':{'type':'string'},'type':{'type':'string','enum':['door','crate','object']},
    'source_quote':{'type':'string'}},
    'required':['name_quote','type','source_quote'],'additionalProperties':False}
SCENE_SCHEMA={'type':'object','properties':{
    'objects':{'type':'array','maxItems':20,'items':OBJECT_SCHEMA}},
    'required':['objects'],'additionalProperties':False}


def extract_scene_objects(description,base_url,complete=None):
    """Return validated rows and per-call input tokens; never author facts."""
    if not isinstance(description,str) or not description.strip():
        raise RuleError('場景描述尚未建立。')
    complete=complete or _complete
    instruction=('只由 scene_description 逐字抽取目前可互動的具體物件，最多 20 件。'
                 'name_quote 必須是物件名稱的逐字片段，source_quote 必須是包含名稱的逐字原句；'
                 '兩者都必須出自 scene_description，不能引用玩家偏好或自行補寫。'
                 '人物、地面、廣場、光線及遠處尚未接觸的地方不是物件。'
                 'type 只選 door、crate 或 object。不確定就不要列入。只回 JSON。')
    messages=[{'role':'system','content':instruction+'\nscene_description:\n'+description}]
    tokens=count(base_url,messages);limit=budget(base_url,500)
    if limit and tokens is not None and tokens>limit:
        raise RuleError('場景物件抽取超過模型容量。')
    raw=complete(messages,base_url,500,.15,response_schema=SCENE_SCHEMA,raw=True)
    data=parse_proposal(raw) if isinstance(raw,str) else raw
    if not isinstance(data,dict) or set(data)!={'objects'} or not isinstance(data['objects'],list):
        raise RuleError('場景物件抽取格式錯誤。')
    accepted=[];rejected=[];names=set()
    for row in data['objects'][:20]:
        if (not isinstance(row,dict) or set(row)!=set(OBJECT_SCHEMA['required']) or
                row['type'] not in ('door','crate') or
                not isinstance(row['name_quote'],str) or len(row['name_quote'].strip())<2 or
                not isinstance(row['source_quote'],str) or len(row['source_quote'].strip())<4 or
                row['source_quote'] not in description or
                row['name_quote'] not in row['source_quote'] or
                row['name_quote'] in names):
            rejected.append(row);continue
        sentence=next((part for part in re.split(r'(?<=[。！？])',description)
                       if row['name_quote'] in part and row['source_quote'] in part),'')
        if not sentence or re.search(r'遠處|遠方|遠端',sentence):
            rejected.append(row);continue
        names.add(row['name_quote'])
        accepted.append({'name':row['name_quote'],'type':row['type'],
                         'source_quote':sentence.strip(),'force_profile':None})
    return accepted,rejected,tokens


def with_scene_objects(plan,rows):
    """Add only validated rows to a copied plan; build_world checks again."""
    candidate=copy.deepcopy(plan)
    candidate['location']['objects']=copy.deepcopy(rows)
    return candidate
