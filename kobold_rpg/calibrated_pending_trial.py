"""Durable preparation of calibrated decisions on an isolated save copy.

This freezes dice and model stages. It does not narrate or commit a turn.
"""
import json

from .calibrated_difficulty_trial import (compile_calibrated_action,
    propose_force_profile,register_force_profile,resolve_profiled_force)
from .dynamic_pending_trial import _dice,_row,_save_once
from .dynamic_values_trial import (propose_object_extension,
                                   register_object_extension,resolve_dynamic_intent)
from .engine import RuleError,require_text
from .structured_state_trial import resolve_values


def prepare_calibrated_decision(engine,request_id,revision,text,base_url,complete=None):
    original=require_text(text,'玩家輸入')
    request_id=require_text(request_id,'行動識別',200)
    # This trial uses a separate pending namespace from the older workflow.
    key='calibrated:'+request_id
    row=_row(engine,key,original,revision)
    state=engine.state()
    if state['revision']!=revision:
        raise RuleError('故事在行動處理期間已更新，原裁定不可套用到新進度。')
    if row['decision'] is not None:return json.loads(row['decision'])
    if row['intent'] is None:
        intent,_=compile_calibrated_action(state,original,base_url,complete)
        intent=_save_once(engine,key,'intent',intent)
    else:intent=json.loads(row['intent'])
    if intent['mode']!='play' or len(intent['steps'])!=1:
        raise RuleError('校準難度試驗只接受單一步驟。')
    proposal=json.loads(row['proposal']) if row['proposal'] is not None else None
    step=intent['steps'][0]
    if step['action']=='force':
        target=step['target_id'];entity=state.get('world',{}).get('entities',{}).get(target)
        if (not step['negated'] and isinstance(entity,dict) and
                entity.get('location')==state['pc']['location'] and
                'force_profile' not in entity and proposal is None):
            proposed,_=propose_force_profile(state,target,base_url,complete)
            register_force_profile(state,target,proposed['tier'],
                proposed['effect_key'],proposed['initial'],proposed['source_quote'],
                proposed['initial_source_quote'])
            proposal=_save_once(engine,key,'proposal',proposed)
        decision=resolve_profiled_force(state,intent,proposal,_dice(row['seed']))
    elif (step['action']=='custom' and not step['negated'] and
          step['target_id'] in state.get('world',{}).get('entities',{})):
        if proposal is None:
            repair=None
            for attempt in range(2):
                proposal,_=propose_object_extension(state,original,step['target_id'],
                                                    base_url,complete,repair)
                try:register_object_extension(state,proposal)
                except RuleError as exc:
                    if attempt:raise
                    repair=(proposal,str(exc))
                else:break
            proposal=_save_once(engine,key,'proposal',proposal)
        intent,decision=resolve_dynamic_intent(state,intent,proposal,_dice(row['seed']))
    else:
        decision=resolve_values(state,intent,_dice(row['seed']))
    return _save_once(engine,key,'decision',{'intent':intent,'proposal':proposal,
                                             'decision':decision})
