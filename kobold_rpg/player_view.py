"""Player knowledge is sourced from presence and delivered narration only."""
import copy
from .physical import scene_text


def encounters(state):
    here = state['pc']['location']
    return [{'id': npc['id'], 'name': npc.get('public_name', npc['name']),
             'description': npc['description'], 'location': here,
             'place': state['locations'][here]['name'],
             'observed_condition':npc.get('player_view',{}).get('condition',{}).get('text') or
                                  (npc['injuries'][-1]['condition'] if npc.get('injuries') else None)}
            for npc in state['npcs'].values() if npc['location'] == here and npc['known']]


def knowledge(state, history):
    people = {}
    visited = {state['pc']['location']}
    for row in history:
        visited.update(row.get('_visited', []))
        for person in row.get('_encounters', []):
            record = people.setdefault(person['id'], {**person, 'facts': [], 'interactions': []})
            record.update(last_seen=person['place'], last_seen_revision=row['revision'])
            if person.get('observed_condition'):record['observed_condition']=person['observed_condition']
    for person in encounters(state):
        record = people.setdefault(person['id'], {**person, 'facts': [], 'interactions': []})
        record.update(last_seen=person['place'], last_seen_revision=state['revision'])
        if person.get('observed_condition'):record['observed_condition']=person['observed_condition']
    for npc_id, person in people.items():
        person['facts'] = [{'kind': 'observed', 'quote': person['description'], 'revision': 0}]
        for note in state.get('people_notes', {}).get(npc_id, []):
            if note['quote'] not in {n['quote'] for n in person['facts']}:
                person['facts'].append(copy.deepcopy(note))
        profile=state['npcs'].get(npc_id,{}).get('player_view',{})
        for note in profile.get('facts',{}).values():
            person['facts'].append({'kind':note['kind'],'quote':note['evidence'],
                                    'summary':note['text'],'revision':note['revision']})
        person['relationship']=profile.get('relationship',{}).get('text') or '關係尚未明朗，會隨你們的相處而變化。'
        if profile.get('condition'):person['observed_condition']=profile['condition']['text']
    return people, visited


def map_view(state, history):
    _, visited = knowledge(state, history)
    origin = history[0].get('_origin', state['pc']['location']) if history else state['pc']['location']
    if origin not in state['locations']:
        origin = state['pc']['location']
    known = {key for key in visited if key in state['locations']}
    queue = sorted(known)
    while queue:
        for target, route in state['locations'][queue.pop(0)]['exits'].items():
            if route['known'] and target in state['locations'] and target not in known:
                known.add(target); queue.append(target)
    depth = {origin: 0} if origin in known else {state['pc']['location']: 0}
    queue = list(depth)
    while queue:
        source = queue.pop(0)
        for target, route in state['locations'][source]['exits'].items():
            if route['known'] and target in known and target not in depth:
                depth[target] = depth[source] + 1; queue.append(target)
    for target in sorted(known - set(depth)):
        depth[target] = max(depth.values(), default=0) + 1
    nodes, links, seen_links = [], [], set()
    layers = {}
    for key, level in depth.items():
        layers.setdefault(level, []).append(key)
    maximum = max(layers, default=0)
    for level, ids in layers.items():
        for index, key in enumerate(sorted(ids)):
            place = state['locations'][key]
            x = 480 if not maximum else 160 + 640 * level / maximum
            y = 100 + 400 * (index + 1) / (len(ids) + 1)
            nodes.append({'id': key, 'name': place['name'], 'x': round(x), 'y': round(y),
                'current': key == state['pc']['location'], 'visited': key in visited,
                'description': scene_text(state) if key == state['pc']['location'] else
                               ('你曾到過這裡，最新情況需要回去確認。' if key in visited else '已知通路上的地方，抵達後再了解當地景物。'),
                'can_travel': bool(state['locations'][state['pc']['location']]['exits'].get(key, {}).get('known'))})
            for target, route in place['exits'].items():
                edge = tuple(sorted((key, target)))
                if route['known'] and target in known and edge not in seen_links:
                    reverse=state['locations'][target]['exits'].get(key,{}).get('known',False)
                    seen_links.add(edge); links.append({'from': key, 'to': target, 'two_way': bool(reverse)})
    return {'nodes': nodes, 'links': links, 'origin': origin, 'scale': '通路示意，不代表實際距離或方向'}


def validate_note(state, event, narration, error):
    if set(event) != {'type', 'npc', 'kind', 'quote'} or event.get('kind') not in {'said', 'observed'}:
        raise error('人物見聞需要人物、來源種類及原文摘錄')
    npc = state['npcs'].get(event.get('npc'))
    if not npc or not npc['known'] or npc['location'] != state['pc']['location']:
        raise error('不能把未遇見人物的秘密寫入玩家見聞')
    quote = event['quote']
    if not isinstance(quote, str) or not 4 <= len(quote) <= 1000 or quote not in narration:
        raise error('人物見聞必須引用本次實際呈現給玩家的敘事，不能引用私人筆記')


def apply_note(state, event, revision):
    notes = state.setdefault('people_notes', {}).setdefault(event['npc'], [])
    if not any(n['kind'] == event['kind'] and n['quote'] == event['quote'] for n in notes):
        notes.append({'kind': event['kind'], 'quote': event['quote'], 'revision': revision})
