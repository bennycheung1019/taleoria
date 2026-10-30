"""Known people may be referenced without being physically present.

Only names and the existing visible scene text are retrieved for distant people.
This grants no reaction, movement, private knowledge or power permission.
"""
import re
from .names import aliases
from .physical import scene_text


def mentions(npc, value, registry):
    parts = [part.strip() for part in re.split(r'[（()）]', npc['name']) if part.strip()]
    names = {npc['id'], *parts, *(registry[part] for part in parts if part in registry)}
    for name in names:
        pattern = (r'(?<![\w])' + re.escape(name) + r'(?![\w])') if name.isascii() else re.escape(name)
        if re.search(pattern, value, re.I):
            return True
    return False


def referenced_characters(state, action=None):
    scene = scene_text(state)
    declaration = action.get('text', '') if action else ''
    registry = aliases(state)
    result = {}
    for key, npc in state['npcs'].items():
        if not npc['known'] or npc['location'] == state['pc']['location']:
            continue
        excerpts = [part.strip() for part in re.split(r'(?<=[。！？])|\n+', scene)
                    if mentions(npc, part, registry)]
        if excerpts or mentions(npc, declaration, registry):
            result[key] = {'id': key, 'name': npc['name'], 'access': 'reference_only',
                           'current_scene_mentions': excerpts,
                           'constraint': '已建立的遠處／被提及人物。只可依玩家已見的敘述提及或觀察；不能假定在身旁、聽見台詞、回應、移動或透露私人資料。'}
    return result


def audit_actor_ids(state, action=None):
    available = {state['pc']['id']} | {key for key, npc in state['npcs'].items()
                                       if npc['location'] == state['pc']['location']}
    available.update(referenced_characters(state, action))
    if action and action['kind'] == 'travel' and action.get('compound'):
        destination = action.get('destination')
        if state['locations'][state['pc']['location']]['exits'].get(destination, {}).get('known'):
            available.update(key for key, npc in state['npcs'].items() if npc['known'] and npc['location'] == destination)
    return sorted(available & set(state.get('canon', {}).get('actors', available)))


def name_options(state, key, entity):
    parts = [part.strip() for part in re.split(r'[（()）]', entity['name']) if part.strip()]
    registry = aliases(state)
    return {entity['name'],key,*parts,*(registry[part] for part in parts if part in registry)}


def named_npc(state, query):
    found = []
    for key, npc in state['npcs'].items():
        if not npc['known']: continue
        if any(re.fullmatch(re.escape(name), query, re.I) for name in name_options(state,key,npc)): found.append(key)
    return found[0] if len(found) == 1 else None


def inspection_target(state, declaration):
    match = re.fullmatch(r'(?:I\s+)?(?:check out|look at|examine|inspect|watch)\s+(.+?)[.!。！]?|(?:我)?(?:查看|看看|打量|觀察|看向)\s*(.+?)[。！!]?'
                         , declaration.strip(), re.I)
    return named_npc(state,(match.group(1) or match.group(2)).strip()) if match else None


def targeted_observation(state, action):
    key = action.get('target')
    if (action['kind'] != 'observe' or key not in state['npcs'] or not state['npcs'][key]['known']
            or action.get('compound') or action.get('understanding', {}).get('mode') == 'mixed'):
        return None
    npc = state['npcs'][key]
    if npc['location'] == state['pc']['location']:
        if not npc['alive']: return npc['name'] + '已死亡。' + '；'.join(npc['conditions'])
        scene = [part.strip() for part in re.split(r'(?<=[。！？])|\n+', scene_text(state))
                 if mentions(npc, part, aliases(state))]
        return '\n'.join(scene or [npc['description']])
    excerpts = referenced_characters(state, action).get(key, {}).get('current_scene_mentions', [])
    if excerpts:
        return '你站在原處觀察。\n' + '\n'.join(excerpts) + '\n從這裡還無法確認更多細節。'
    return '你看向四周，眼前沒有可確認的' + npc['name'] + '身影。'
