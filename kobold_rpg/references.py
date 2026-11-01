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


def name_options(state, key, entity):
    parts = [part.strip() for part in re.split(r'[（()）]', entity['name']) if part.strip()]
    registry = aliases(state)
    return {entity['name'],key,*parts,*(registry[part] for part in parts if part in registry)}
