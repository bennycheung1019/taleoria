"""Small, bounded checks for copied prose before a new turn is committed."""
from difflib import SequenceMatcher


def repeated_passage(narration, recent, *, minimum=100, fraction=.45):
    """Find substantial verbatim reuse; short recurring names/dialogue are fine."""
    if not isinstance(narration,str) or not narration:
        return False
    current=narration[:5000]
    for row in recent or []:
        previous=row.get('narration','') if isinstance(row,dict) else ''
        if not isinstance(previous,str):
            continue
        match=SequenceMatcher(None,current,previous[:5000],autojunk=False).find_longest_match(
            0,len(current),0,min(len(previous),5000))
        if match.size>=minimum and match.size>=len(current)*fraction:
            return True
    return False
