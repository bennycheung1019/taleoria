"""Player-facing encounters keep each person's first observed description."""
from .physical import scene_text


def encounters(state):
    from .npc_visibility import public_name
    here = state['pc']['location']
    return [{'id': npc['id'], 'name': public_name(npc),
             'description': npc['description'], 'location': here,
             'place': state['locations'][here]['name']}
            for npc in state['npcs'].values() if npc['location'] == here and npc['known']]


def knowledge(state, history):
    from .npc_visibility import name_known
    named={key for key,npc in state['npcs'].items() if name_known(npc)}
    people = {}
    visited = {state['pc']['location']}
    def first_impression(person):
        return {key:person[key] for key in ('id','name','description','location','place')}
    for row in history:
        visited.update(row.get('_visited', []))
        for person in row.get('_encounters', []):
            if person['id'] not in named:continue
            record = people.setdefault(person['id'], first_impression(person))
            record.update(last_seen=person['place'], last_seen_revision=row['revision'])
    for person in encounters(state):
        if person['id'] not in named:continue
        record = people.setdefault(person['id'], first_impression(person))
        record.update(name=person['name'],last_seen=person['place'], last_seen_revision=state['revision'])
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
