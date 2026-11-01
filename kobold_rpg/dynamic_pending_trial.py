"""Disposable trial: freeze a dynamic action decision across request retries.

This prepares a decision on an isolated SQLite save. It does not narrate,
commit a story turn, or wire the trial into the live API.
"""
import hashlib
import hmac
import json
import secrets

from .dynamic_values_trial import (propose_object_extension,
                                   register_object_extension,resolve_dynamic_intent)
from .engine import RuleError,canonical,require_text
from .structured_state_trial import compile_action


def _dice(seed):
    counter=0
    def roll(sides):
        nonlocal counter
        counter+=1
        digest=hmac.new(bytes.fromhex(seed),counter.to_bytes(8,'big'),hashlib.sha256).digest()
        return int.from_bytes(digest,'big')%sides+1
    return roll


def _row(engine,request_id,text,revision):
    with engine.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS dynamic_trial_pending (
            request_id TEXT PRIMARY KEY, action_text TEXT NOT NULL,
            revision INTEGER NOT NULL, seed TEXT NOT NULL,
            intent TEXT, proposal TEXT, decision TEXT)''')
        existing=db.execute('SELECT * FROM dynamic_trial_pending WHERE request_id=?',
                            (request_id,)).fetchone()
        if existing is None:
            db.execute('INSERT INTO dynamic_trial_pending '
                       '(request_id,action_text,revision,seed) VALUES (?,?,?,?)',
                       (request_id,text,revision,secrets.token_hex(32)))
            existing=db.execute('SELECT * FROM dynamic_trial_pending WHERE request_id=?',
                                (request_id,)).fetchone()
        if existing['action_text']!=text or existing['revision']!=revision:
            raise RuleError('同一行動識別不能改動宣告或起始進度。')
        return dict(existing)


def _save_once(engine,request_id,field,value):
    if field not in ('intent','proposal','decision'):raise ValueError(field)
    data=canonical(value)
    with engine.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute(f'UPDATE dynamic_trial_pending SET {field}=? '
                   f'WHERE request_id=? AND {field} IS NULL',(data,request_id))
        chosen=db.execute(f'SELECT {field} FROM dynamic_trial_pending WHERE request_id=?',
                          (request_id,)).fetchone()
    return json.loads(chosen[0])


def prepare_dynamic_decision(engine,request_id,revision,text,base_url,complete=None):
    """Return a stored decision, repeating only an interrupted model stage.

    The seed is persisted before any model call. If a crash happens after a
    proposal and before the decision write, the same dice are used on retry.
    """
    original=require_text(text,'玩家輸入')
    request_id=require_text(request_id,'行動識別',200)
    row=_row(engine,request_id,original,revision)
    state=engine.state()
    if state['revision']!=revision:
        raise RuleError('故事在行動處理期間已更新，原裁定不可套用到新進度。')
    if row['decision'] is not None:
        return json.loads(row['decision'])
    if row['intent'] is None:
        intent,_=compile_action(state,original,base_url,complete)
        intent=_save_once(engine,request_id,'intent',intent)
    else:intent=json.loads(row['intent'])
    if intent['mode']!='play' or len(intent['steps'])!=1:
        raise RuleError('動態動作試驗只接受單一步驟。')
    proposal=json.loads(row['proposal']) if row['proposal'] is not None else None
    step=intent['steps'][0]
    if step['action']=='custom' and not step['negated'] and proposal is None:
        repair=None
        for attempt in range(2):
            proposal,_=propose_object_extension(state,original,step['target_id'],
                                                base_url,complete,repair)
            try:register_object_extension(state,proposal)
            except RuleError as exc:
                if attempt:raise
                repair=(proposal,str(exc))
            else:break
        proposal=_save_once(engine,request_id,'proposal',proposal)
    resolved_intent,decision=resolve_dynamic_intent(state,intent,proposal,_dice(row['seed']))
    frozen={'intent':resolved_intent,'proposal':proposal,'decision':decision}
    return _save_once(engine,request_id,'decision',frozen)
