"""Visible scene text with current injuries and stances."""
import re

def scene_text(state):
    text=state['locations'][state['pc']['location']]['description'];additions=[]
    for npc in state['npcs'].values():
        changed=npc.get('injuries') or re.search(r'警戒|防衛|交戰|持劍相向|正在攻擊',npc.get('encounter',{}).get('stance',''))
        if not changed:continue
        names=[part for part in re.split(r'[（()）]',npc['name']) if part]
        text=''.join(part for part in re.split(r'(?<=[。！？])|\n+',text) if not any(name in part for name in names))
        if npc['known'] and npc['location']==state['pc']['location']:
            additions.append(npc['name']+'：'+(npc['injuries'][-1]['condition'] if npc.get('injuries') else npc['encounter']['stance']))
    return '\n'.join([text.strip(),*additions]).strip() or '這裡是'+state['locations'][state['pc']['location']]['name']+'。'
