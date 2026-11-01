"""Keep standalone protocol tails out of prose without rewriting the journal."""
import re


_TAIL=re.compile(r'(?m)^[ \t]*(?:[},][ \t]*)?(?:\{[ \t]*)?["\']?'
    r'(?:changes|establish|player_power_uses|scene_focus|npcs)["\']?[ \t]*:[ \t]*(?=[{\[])')


def story_text(value):
    if not isinstance(value,str):return value
    for match in _TAIL.finditer(value):
        # Preserve intentional code examples within a fenced passage. Ordinary
        # dialogue containing words such as "changes" never matches this shape.
        prefix=value[:match.start()]
        if len(re.findall(r'(?m)^[ \t]*```',prefix))%2:continue
        return prefix.rstrip()
    return value
