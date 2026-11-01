"""Resolve an unaddressed conversation from durable, local scene contact."""
import re

from .names import PAIR, chinese
from .npc_visibility import public_name


def present_people(state):
    here = state['pc']['location']
    return {key: npc for key, npc in state['npcs'].items()
            if npc.get('known') and npc.get('alive', True) and npc.get('location') == here}


def _said_name(text, name):
    if not name:
        return False
    pattern = (r'(?<![A-Za-z])' + re.escape(name) + r'(?![A-Za-z])'
               if name.isascii() else re.escape(name))
    return bool(re.search(pattern, text, re.I))


def explicit_people(state, text):
    """Use spoken names and visible labels, never undisclosed private names."""
    found = []
    for key, npc in present_people(state).items():
        visible = public_name(npc)
        labels = [visible]
        role = npc.get('role', '')
        if role:
            labels.append(role)
        if '的' in visible:
            labels.append(visible.rsplit('的', 1)[-1])
        cues = role + visible
        if re.search(r'年輕|青年|二十', cues):
            labels.extend(('年輕人', '青年', 'young person', 'young man'))
        if re.search(r'老者|老人|年長|六旬|老漁', cues):
            labels.extend(('老者', '老人', 'old man', 'elderly man'))
        if npc.get('name_known', True):
            labels.append(chinese(npc['name']))
            match = PAIR.fullmatch(npc['name'].strip())
            if match:
                labels.append(match[2])
        if any(_said_name(text, label) for label in labels):
            found.append(key)
    return found


def last_interlocutor(state):
    """Old saves fall back to scene focus; newer turns record a precise ID."""
    present = present_people(state)
    memory = state.get('scene_memory', {})
    here = state['pc']['location']
    last = memory.get('interlocutor', {}).get(here)
    if last in present:
        return last
    for key in reversed(memory.get('focus', {}).get(here, [])):
        if key in present:
            return key
    return None


def conversation_target(state, text):
    named = explicit_people(state, text)
    if len(named) == 1:
        return named[0]
    if len(named) > 1:
        return None
    last = last_interlocutor(state)
    if last:
        return last
    present = present_people(state)
    return next(iter(present)) if len(present) == 1 else None
