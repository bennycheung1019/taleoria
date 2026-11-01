"""Keep a character's private identity separate from what the player knows."""
import copy
import re

from .names import PAIR, chinese


def name_known(npc):
    # Older campaigns disclosed names at first sight; preserve their history.
    return npc.get('name_known', True) is True


def appearance_label(description):
    first = re.split(r'[，。；,;\n]', description or '')[0].strip()
    first = re.split(r'正在|正要|正提|正拿|站在|坐在', first)[0].strip()
    return first[:32] if len(first) >= 3 else '一位在場的人'


def public_name(npc):
    if name_known(npc):
        return npc['name']
    short = chinese(npc.get('name', ''))
    label = npc.get('public_name', '')
    if label and short not in label:
        return label
    description = npc.get('description', '').replace(npc.get('name', ''), '').replace(short, '')
    return appearance_label(description)


def hide_name(text, npc, *, before=None):
    """Use the visual label until a witnessed introduction in this turn."""
    if not isinstance(text, str):
        return text
    label = public_name({**npc, 'name_known': False})
    canonical = npc.get('name', '')
    short = chinese(canonical)
    if not short:
        return text
    end = len(text) if before is None else before
    left, right = text[:end], text[end:]
    # A hidden internal name cannot be introduced by inventing a player-given
    # nickname. Remove that unsupported aside before masking the name itself.
    for candidate in (canonical, short):
        if candidate:
            left = re.sub(r'——\s*你(?:稱呼|叫|喊|稱)(?:他|她|佢)(?:為|做)?\s*' +
                          re.escape(candidate) + r'\s*——', '', left)
    left = left.replace(canonical, label)
    if short != canonical and len(short) > 1:
        left = left.replace(short, label)
    pair = PAIR.fullmatch(canonical.strip())
    if pair:
        left = re.sub(r'(?<![A-Za-z])' + re.escape(pair[2]) + r'(?![A-Za-z])', label, left, flags=re.I)
    return left + right


def introduction_at(text, npc):
    """Only speech that actually states the name makes it public."""
    short = chinese(npc.get('name', ''))
    if not short or not isinstance(text, str):
        return None
    names=[re.escape(short) + r'(?![\u3400-\u9fff])']
    pair=PAIR.fullmatch(npc.get('name','').strip())
    if pair:names.append(re.escape(pair[2]) + r'(?![A-Za-z])')
    match = re.search(r'「[^」]{0,100}(?:我叫|我是|我係|叫我|你可以叫我|大家叫我)\s*(?:' +
                      '|'.join(names) + r')', text, re.I)
    return match.start() if match else None


def reconcile_reply(state, reply):
    """Redact unrevealed names and persist an evidenced name disclosure."""
    result = copy.deepcopy(reply)
    prose = result.get('narration')
    if not isinstance(prose, str):
        return result
    changes = result.setdefault('changes', {})
    if not isinstance(changes, dict):
        changes = result['changes'] = {}
    patches = changes.setdefault('npcs', {})
    if not isinstance(patches, dict):
        patches = changes['npcs'] = {}
    for key, patch in patches.items():
        if key in state.get('npcs', {}) and name_known(state['npcs'][key]) and isinstance(patch, dict):
            patch.pop('name_known', None)
            patch.pop('public_name', None)
    people = {**state.get('npcs', {})}
    for key, patch in patches.items():
        if key not in people and isinstance(patch, dict) and isinstance(patch.get('name'), str):
            people[key] = {**patch, 'name_known': False, 'public_name': ''}
    for key, npc in people.items():
        if not isinstance(npc, dict) or name_known(npc):
            continue
        label = public_name(npc)
        intro = introduction_at(prose, npc)
        prose = hide_name(prose, npc, before=intro)
        patch = patches.setdefault(key, {})
        if not isinstance(patch, dict):
            continue
        patch['public_name'] = npc['name'] if intro is not None else label
        patch['name_known'] = intro is not None
    result['narration'] = prose
    return result


def public_plan(plan, seed):
    """Return only fields needed by the draft UI, without private NPC data."""
    result = copy.deepcopy(plan)
    npc = seed['npcs']['guide']
    if name_known(npc):
        return result
    for key in ('title', 'background'):
        result[key] = hide_name(result[key], npc)
    result['opening'] = opening_for_player(plan, seed)
    result['rules'] = [hide_name(value, npc) for value in result['rules']]
    for place in [result['location'], *result['location'].get('nearby', [])]:
        for key in ('name', 'description'):
            place[key] = hide_name(place[key], npc)
    crowd = seed['locations']['start'].get('crowd', '')
    if crowd and crowd not in result['location']['description']:
        result['location']['description'] += '\n' + crowd
    result['npc'] = {'name': public_name(npc),
                     'description': hide_name(result['npc']['description'], npc)}
    return mask_hidden(result, seed)


def opening_for_player(plan, seed):
    npc = seed['npcs']['guide']
    text = hide_name(plan['opening'], npc) if not name_known(npc) else plan['opening']
    crowd = seed['locations']['start'].get('crowd', '')
    if crowd and not re.search(r'幾位|幾個|一些|人群|路人|居民們|攤販們|行人', text):
        text += '\n\n' + crowd
    return text


def mask_hidden(value, state):
    hidden = [npc for npc in state.get('npcs', {}).values() if not name_known(npc)]
    if isinstance(value, str):
        for npc in hidden:
            value = hide_name(value, npc)
        return value
    if isinstance(value, list):
        return [mask_hidden(item, state) for item in value]
    if isinstance(value, dict):
        return {key: mask_hidden(item, state) for key, item in value.items()}
    return value
