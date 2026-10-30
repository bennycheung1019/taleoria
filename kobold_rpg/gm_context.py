"""Read-only chronology for the GM, without judging or rewriting play."""
import json


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
        recent.append({'revision':record['revision'],'declaration':row['action']['text'],'narration':row['narration'],
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
