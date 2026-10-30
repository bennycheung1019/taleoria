"""Resolve plain movement to known people/places before asking for a story.

No guess of a hidden NPC's position, no implicit extra action or teleport.
"""
import re
from .references import named_npc,name_options,referenced_characters

MOVE=re.compile(
    r'(?:please\s+)?(?:I\s+)?(?:'
    r'(?:get|move|come|go)\s+(?:(?:a\s+bit|a\s+little|slightly)\s+)?clos(?:e|er)\s+to'
    r'|(?:walk|move|go|head|come)(?:\s+(?:over|up))?\s+(?:to|towards?)'
    r'|approach)\s+(.+?)[.!。！]?'
    r'|(?:我)?(?:走近|靠近|接近|走向|走到|前往|去)\s*(.+?)[。！!]?$',re.I)


def movement_query(declaration):
    """Shared by speech-act recognition and movement routing; keep raw text."""
    match=MOVE.fullmatch(declaration.strip())
    return (match.group(1) or match.group(2)).strip() if match else None


def _pattern(names):
    return '(?:'+'|'.join(re.escape(name) for name in sorted(names,key=len,reverse=True))+')'


def known_person_destination(state,key):
    npc=state['npcs'][key];here=state['pc']['location']
    if npc['location']==here:return here
    reference=referenced_characters(state).get(key)
    if not reference:return None
    person=_pattern(name_options(state,key,npc))
    # Require an affirmative public location cue, not merely a name in a wish
    # or a sentence saying the person isn't there. Do not disclose canonical
    # locations or private movement to route an unlocated person.
    found=set()
    for destination,route in state['locations'][here]['exits'].items():
        if not route.get('known') or destination not in state['locations']:continue
        place=_pattern(name_options(state,destination,state['locations'][destination]))
        patterns=[place+r'(?:的|旁的|附近的|邊的)\s*'+person,
                  person+r'\s*(?:正)?(?:在|位於|站在|坐在)\s*'+place,
                  person+r'\s+(?:(?:is|stands|standing)\s+)?(?:at|in|near)\s+(?:the\s+)?'+place]
        for excerpt in reference['current_scene_mentions']:
            if re.search(r'不在|沒在|沒有在|離開|聽說|據說|傳聞|\b(?:not|rumou?r|heard|left)\b',excerpt,re.I):continue
            if any(re.search(pattern,excerpt,re.I) for pattern in patterns):found.add(destination)
    return next(iter(found)) if len(found)==1 else None


def movement(state,declaration):
    query=movement_query(declaration)
    if query is None:return None
    person=named_npc(state,query)
    here=state['pc']['location']
    places=[key for key,place in state['locations'].items()
            if (key==here or state['locations'][here]['exits'].get(key,{}).get('known'))
            and any(re.fullmatch(re.escape(name),query,re.I) for name in name_options(state,key,place))]
    if person and places:return None
    if person:
        destination=known_person_destination(state,person)
        if destination==here:return {'kind':'interact','target':person}
        if destination:return {'kind':'travel','destination':destination,'target':''}
    elif len(places)==1 and places[0]!=here:
        return {'kind':'travel','destination':places[0],'target':''}
    return None
