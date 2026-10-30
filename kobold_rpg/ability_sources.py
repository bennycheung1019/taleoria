"""Check declared player power effects against sources from before the turn.

This module does not parse player wording or adjudicate ordinary actions.
"""
import copy


def source_for(state,ability_id):
    if not isinstance(ability_id,str) or not ability_id:return None
    pc=state['pc']
    if ability_id in pc.get('spells',[]):
        definition=state.get('abilities',{}).get(ability_id)
        if isinstance(definition,dict) and definition.get('source') and definition.get('effect'):
            return {'kind':'learned_spell','id':ability_id,'definition':copy.deepcopy(definition)}
    identity=state.get('canon',{}).get('actors',{}).get(pc['id'],{})
    if ability_id in identity.get('powers',[]):
        definition=state.get('canon',{}).get('powers',{}).get(ability_id)
        if (isinstance(definition,dict) and definition.get('actor')==pc['id']
                and definition.get('source') and definition.get('effect')
                and type(definition.get('established_revision')) is int
                and definition['established_revision']<=state['revision']):
            return {'kind':'registered_power','id':ability_id,'definition':copy.deepcopy(definition)}
    return None


def inspect_uses(state,uses):
    issues=[];checked=[]
    if not isinstance(uses,list):
        return [{'ability_id':'','reason':'能力使用資料未能核對來源'}],checked
    for use in uses:
        if (not isinstance(use,dict) or not isinstance(use.get('ability_id'),str)
                or type(use.get('manifested')) is not bool):
            issues.append({'ability_id':'','reason':'能力使用資料未能核對來源'});continue
        key=use['ability_id'];source=source_for(state,key)
        if not use['manifested']:
            checked.append({'ability_id':key,'result':'no_effect','source_found':source is not None})
        elif source is None:
            issues.append({'ability_id':key,'reason':'本回合開始前沒有已學或已登記的可用能力來源；這次宣告和草案不能補造來源'})
        else:
            checked.append({'ability_id':key,'result':'source_confirmed','source':source})
    return issues,checked


def inspect_reply(state,reply):
    uses=reply.get('player_power_uses',[])
    issues,checked=inspect_uses(state,uses)
    unknown_attempt=any(isinstance(use,dict) and source_for(state,use.get('ability_id')) is None
                        for use in uses) if isinstance(uses,list) else False
    changes=reply.get('changes',{})
    if unknown_attempt and isinstance(changes,dict):
        pc=changes.get('pc',{})
        spells=pc.get('spells') if isinstance(pc,dict) else None
        canon=changes.get('canon',{})
        actors=canon.get('actors',{}) if isinstance(canon,dict) else {}
        actor=actors.get(state['pc']['id'],{}) if isinstance(actors,dict) else {}
        powers=actor.get('powers') if isinstance(actor,dict) else None
        owned=state.get('canon',{}).get('actors',{}).get(state['pc']['id'],{}).get('powers',[])
        new_spells=isinstance(spells,list) and any(key not in state['pc'].get('spells',[]) for key in spells)
        new_powers=isinstance(powers,list) and any(key not in owned for key in powers)
        if new_spells or new_powers:
            issues.append({'ability_id':'','reason':'不能從這次未具備能力的嘗試，自行新增玩家能力來補造來源；學習或取得能力須另外有已成立的來源'})
    return issues,checked
