"""Small, conservative input conveniences. Ambiguity stays Freeform review."""
import re
from .engine import normalize_action, require_text
from .physical import attacking
from .understanding import understand,action_text
from .references import inspection_target,mentions
from .names import aliases
from .navigation import movement


def interpret(state,text,intent=None,resolver=None):
    original=require_text(text,'你想做的事')
    understanding=understand(original,resolver)
    mode=understanding['mode']
    lexical='\n'.join(understanding['actions']) if understanding['actions'] else original
    action=_route_action(state,lexical,intent if mode in {'action','mixed'} else None,allow_inspection=mode=='action')
    action['text']=original
    if mode=='speech':
        action.update(kind='speak',ability='',item='',destination='')
        present=[npc for npc in state['npcs'].values() if npc['known'] and npc['location']==state['pc']['location']]
        if not action['target'] and len(present)==1:action['target']=present[0]['id']
    elif mode=='thought':action.update(kind='freeform',target='',ability='',item='',destination='')
    action['understanding']=understanding
    return normalize_action(action)


def _route_action(state, text, intent=None, allow_inspection=True):
    text = require_text(text, '你想做的事')
    here = state['pc']['location']
    present = [n for n in state['npcs'].values() if n['location'] == here and n['known']]
    matches = []
    registry = aliases(state)
    for npc in present:
        if mentions(npc,text,registry):
            matches.append(npc['id'])
    target = matches[0] if len(matches) == 1 else ''
    action = {'kind': 'freeform', 'text': text, 'target': target}
    # Resolve an explicit pronoun only when the scene has one possible person.
    # Do this for item shortcuts too: the item choice does not select a victim.
    pronoun=re.search(r'\b(?:him|her|his|hers)\b|他|她',text,re.I)
    if not target and not matches and pronoun and len(present)==1:
        action['target']=target=present[0]['id']
    if intent is not None:
        return normalize_action({**intent,'target':intent.get('target') or target,'text':text})
    navigation = movement(state,text) if allow_inspection else None
    if navigation:
        return normalize_action({**action,**navigation})
    inspected = inspection_target(state, text) if allow_inspection else None
    if inspected:
        return normalize_action({**action,'kind':'observe','target':inspected})
    named_power = [key for key, rule in state['abilities'].items()
                   if rule['name'] in text and re.search(r'使用|施放|施展|使出|\bcast\b|\buse\b', text, re.I)]
    compact = text.strip().strip('。.!！?？')
    if compact in {'環顧四周', '觀察四周', '我環顧四周', '我觀察眼前環境', 'look around'}:
        action['kind'] = 'observe'
    elif re.match(r'^(?:我)?(?:問|說|告訴|對.*說)|^(?:ask|say|tell)\b|^[「『“"\'‘]', text.replace('\\"','"').replace("\\'","'"), re.I):
        action['kind'] = 'speak'
        if not target and len(present) == 1:
            action['target'] = present[0]['id']
    elif named_power or re.search(r'施放|施展|使出.*(?:法術|魔法)|使用.*(?:魔法|法術)|\bcast\b|\buse\b.*\bmagic\b', text, re.I):
        found = [key for key, rule in state['abilities'].items() if rule['name'] in text or key in text]
        action.update(kind='cast', ability=found[0] if len(found) == 1 else ('fire_magic' if re.search(r'火|fire', text, re.I) else 'unestablished_power'))
    elif re.match(r'^(?:我)?(?:使用|用)|^use\b', text, re.I):
        found = mentioned_items(state,text)
        if len(found) == 1:
            action.update(kind='use_item', item=found[0])
    elif re.match(r'^(?:我)?(?:等待|稍作等待|等一會)|^wait\b', text, re.I):
        action['kind'] = 'wait'
    if action['kind']=='freeform' and attacking(action):
        found=mentioned_items(state,text)
        if len(found)==1:action.update(kind='use_item',item=found[0])
    return normalize_action(action)


def mentioned_items(state,text):
    defaults={'hunting_knife':['獵刀','knife','hunting knife'],'rain_cloak':['雨斗篷','rain cloak'],'rope':['繩索','rope']}
    found=[]
    for key,quantity in state['pc']['inventory'].items():
        if quantity<=0:continue
        names=[state.get('item_catalog',{}).get(key,{}).get('name',''),*defaults.get(key,[key])]
        if any(name and re.search((r'\b'+re.escape(name)+r'\b') if name.isascii() else re.escape(name),text,re.I) for name in names):found.append(key)
    return found
