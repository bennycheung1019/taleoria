"""Read-only chronology for the GM, without judging or rewriting play."""
import json
from .story_text import story_text


MISSING=object()


def at(value,path):
    for key in path:
        if not isinstance(value,dict) or key not in value:return MISSING
        value=value[key]
    return value


def recent_context(engine,state,limit=4,scan=32):
    with engine.connect() as db:
        records=[{'revision':row['revision'],'body':json.loads(row['body']),
                  'before':json.loads(row['before_state']),'after':json.loads(row['after_state'])}
                 for row in db.execute('SELECT revision,body,before_state,after_state FROM journal ORDER BY revision DESC LIMIT ?', (scan,))]
    recent=[]
    for record in records:
        row=record['body'];before=record['before']
        if row['status']!='approved':continue
        recent.append({'revision':record['revision'],'declaration':row['action']['text'],'narration':story_text(row['narration']),
                       'bookkeeping':row.get('bookkeeping','ready'),'location':before['pc']['location'],
                       'witnesses':[key for key,npc in before['npcs'].items()
                                    if npc['known'] and npc['location']==before['pc']['location']]})
        if len(recent)==limit:break
    here=state['pc']['location']
    paths=[('pc','location'),('pc','equipment_notes'),('pc','conditions'),('locations',here,'description')]
    for key,npc in state['npcs'].items():
        if not npc.get('known') or npc.get('location')!=here:continue
        paths.extend(('npcs',key,'encounter',field) for field in npc.get('encounter',{}))
        paths.extend([('npcs',key,'description'),('npcs',key,'inner_life','personality'),
                      ('npcs',key,'inner_life','current_emotions')])
    fields={}
    for path in paths:
        if at(state,path) is MISSING:continue
        changed=next((record['revision'] for record in records
                      if at(record['before'],path)!=at(record['after'],path)),None)
        if changed is not None:source={'last_changed_revision':changed}
        elif not records or records[-1]['revision']==1:source={'last_changed_revision':0}
        else:source={'last_changed_before_revision':records[-1]['revision']}
        fields['.'.join(path)]=source
    return list(reversed(recent)),{
        'snapshot_revision':state['revision'],'field_history':fields,
        'scope':'版本只標示欄位何時實際改變，不代表舊值自動失效。初始場景與早期評價可能尚未隨後續事件整理；由主持人依已接受的事件處理矛盾。'}


def recalled_context(engine,state,text,exclude=()):
    """Retrieve older exact exchanges for named known people, without an LLM."""
    from .names import aliases,chinese
    from .references import mentions
    registry=aliases(state)
    ids=[key for key,npc in state['npcs'].items() if npc.get('known') and mentions(npc,text,registry)][:6]
    if not ids:return []
    placeholders=','.join('?' for _ in ids)
    clauses=[f"EXISTS(SELECT 1 FROM json_each(journal.body,'$.gm_references') WHERE value IN ({placeholders}))",
             f"EXISTS(SELECT 1 FROM json_each(journal.body,'$.gm_changes.npcs') WHERE key IN ({placeholders}))"]
    params=[*ids,*ids]
    for key in ids:
        name=chinese(state['npcs'][key]['name'])
        clauses.append("instr(json_extract(body,'$.narration'),?)>0");params.append(name)
    with engine.connect() as db:
        rows=db.execute("SELECT revision,body FROM journal WHERE json_extract(body,'$.status')='approved' AND ("+' OR '.join(clauses)+") ORDER BY revision DESC LIMIT 12",params).fetchall()
    ignored=set(exclude);result=[]
    for row in rows:
        if row['revision'] in ignored:continue
        body=json.loads(row['body']);narration=story_text(body['narration'])
        result.append({'revision':row['revision'],'declaration':body['action']['text'][:240],
            'narration':narration[:800],'excerpted':len(narration)>800,'referenced_people':ids,
            'scope':'已發生的原文回取，不代表所有在場者都聽到。沿用當時可感知資訊，不重新執行。'})
        if len(result)==2:break
    return list(reversed(result))
