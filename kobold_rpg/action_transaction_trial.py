"""Disposable trial: durable, idempotent action decision before narration.

Only call this against an isolated save copy. This module is not wired into
the browser/API. A failed narration remains pending with its original dice.
"""
import hashlib
import hmac
import json
import secrets

from .action_registry_trial import resolve
from .action_workflow_trial import (audit_narration, assign_missing_difficulties,
                                    compile_intent, narrate)
from .engine import RuleError, canonical, require_text


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
        db.execute('''CREATE TABLE IF NOT EXISTS action_trial_pending (
            request_id TEXT PRIMARY KEY, action_text TEXT NOT NULL,
            revision INTEGER NOT NULL, seed TEXT NOT NULL,
            intent TEXT, decision TEXT, narration TEXT, audit TEXT)''')
        existing=db.execute('SELECT * FROM action_trial_pending WHERE request_id=?',
                            (request_id,)).fetchone()
        if existing is None:
            db.execute('INSERT INTO action_trial_pending(request_id,action_text,revision,seed) VALUES (?,?,?,?)',
                       (request_id,text,revision,secrets.token_hex(32)))
            existing=db.execute('SELECT * FROM action_trial_pending WHERE request_id=?',
                                (request_id,)).fetchone()
        if existing['action_text']!=text or existing['revision']!=revision:
            raise RuleError('同一行動識別不能改動宣告或起始進度。')
        return dict(existing)


def _save(engine,request_id,field,value):
    if field not in ('intent','decision','narration','audit'):
        raise ValueError(field)
    with engine.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute(f'UPDATE action_trial_pending SET {field}=? WHERE request_id=?',
                   (canonical(value) if field in ('intent','decision','audit') else value,request_id))


def run_pending_turn(engine,request_id,revision,text,base_url,complete=None):
    """Compile, freeze dice/decision, audit narration, then commit exactly once.

    An interrupted retry can repeat model narration, but never changes the
    stored decision or dice. Revision conflicts stop before a new decision.
    """
    original=require_text(text,'玩家輸入')
    request_id=require_text(request_id,'行動識別',200)
    row=_row(engine,request_id,original,revision)
    with engine.connect() as db:
        prior=db.execute('SELECT body,after_state FROM journal WHERE request_id=?',
                         (request_id,)).fetchone()
    if prior:
        body=json.loads(prior['body'])
        return {'status':'committed','narration':body['narration'],
                'decision':json.loads(row['decision']) if row['decision'] else None,
                'revision':json.loads(prior['after_state'])['revision']}
    state=engine.state()
    if state['revision']!=revision:
        raise RuleError('故事在行動處理期間已更新，原裁定不可套用到新進度。')
    if row['intent'] is None:
        intent,_=compile_intent(state,original,base_url,complete)
        intent,_=assign_missing_difficulties(state,original,intent,base_url,complete)
        _save(engine,request_id,'intent',intent)
    else:
        intent=json.loads(row['intent'])
    if row['decision'] is None:
        decision=resolve(state,intent,_dice(row['seed']))
        _save(engine,request_id,'decision',decision)
    else:
        decision=json.loads(row['decision'])
    if row['narration'] is None or row['audit'] is None:
        narration,_=narrate(state,original,decision,base_url,complete)
        audit,_=audit_narration(state,original,decision,narration,base_url,complete)
        _save(engine,request_id,'narration',narration)
        _save(engine,request_id,'audit',audit)
    else:
        narration=row['narration']
    # The existing RPG OS writer can fall back to a plain reply on malformed
    # changes. Never let that silently discard the host's resolved effect.
    from .gm import record_changes
    projected,bookkeeping=record_changes(state,decision['changes'],revision+1,narration)
    if bookkeeping!='ready':
        raise RuleError('裁定結果未能完整寫入存檔，故事未執行。')
    patch=decision['changes']
    if 'pc' in patch and projected['pc']['location']!=patch['pc']['location']:
        raise RuleError('存檔位置與裁定不一致，故事未執行。')
    if 'world' in patch:
        for key in ('entities','action_rules'):
            if key in patch['world'] and projected.get('world',{}).get(key)!=patch['world'][key]:
                raise RuleError('存檔世界狀態與裁定不一致，故事未執行。')
    result=engine.record_gm_reply(original,{'narration':narration,
                                            'changes':decision['changes']},request_id,revision)
    return {'status':'committed','narration':result['narration'],
            'decision':decision,'revision':result['revision']}
