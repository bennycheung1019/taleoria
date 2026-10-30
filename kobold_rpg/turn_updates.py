"""Durable, post-story character indexing. Never changes physical world facts."""
import copy
import json
import threading
from .engine import RuleError, canonical, validate_proposal
from .social import apply_social
from .player_view import apply_note

ALLOWED={'social_experience','personality_change','character_note'}


def latest(engine):
    with engine.connect() as db:
        row=db.execute("SELECT * FROM turn_updates WHERE status!='done' ORDER BY source_revision LIMIT 1").fetchone()
    return dict(row) if row else None


def status(engine):
    row=latest(engine)
    return {'status':row['status'] if row else 'ready','source_revision':row['source_revision'] if row else None,
            'revision':engine.state()['revision']}


def enqueue(db, state, action, proposal, source_revision):
    # Observation, navigation and other simple actions need no extra AI call.
    target=action.get('target')
    from .physical import attacking
    if (action['kind'] not in {'speak','interact','freeform'} and not attacking(action)) or target not in state['npcs'] or proposal['outcome']=='clarify':return
    body={'action':action,'narration':proposal['narration'],'target':target}
    db.execute('INSERT OR IGNORE INTO turn_updates(source_revision,body,status) VALUES(?,?,?)',
               (source_revision,canonical(body),'pending'))


def complete(engine, source_revision, events):
    with engine.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        job=db.execute('SELECT * FROM turn_updates WHERE source_revision=?',(source_revision,)).fetchone()
        if not job or job['status']=='done':return
        state=json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
        if state['revision']!=source_revision:raise RuleError('故事版本已改變，不能套用較早的人物整理。')
        body=json.loads(job['body'])
        if not isinstance(events,list) or len(events)>6 or any(not isinstance(e,dict) or e.get('type') not in ALLOWED for e in events):
            raise RuleError('人物整理只能補充已發生經歷與公開見聞。')
        if any(e.get('npc')!=body['target'] for e in events):raise RuleError('人物整理混入另一個人物。')
        source=db.execute('SELECT before_state,body FROM journal WHERE revision=?',(source_revision,)).fetchone()
        original=json.loads(source['before_state']);accepted=json.loads(source['body'])
        if accepted['narration']!=body['narration'] or accepted['action']!=body['action']:
            raise RuleError('人物整理與已接受的故事不一致。')
        # The source turn proves who perceived the encounter, even if its physical
        # outcome moved that person away. Only social fields are copied back.
        context=copy.deepcopy(state)
        context['pc']['location']=original['pc']['location']
        for key in context['npcs']:
            if key in original['npcs']:context['npcs'][key]['location']=original['npcs'][key]['location']
        proposal={'outcome':'success','reason':'只整理已接受故事的人物經歷。','narration':body['narration'],'events':events}
        validate_proposal(context,body['action'],proposal)
        after=copy.deepcopy(state)
        for index,event in enumerate(events):
            if event['type']=='character_note':apply_note(after,event,state['revision']+1)
            else:
                apply_social(context,body['action'],event,state['revision']+1,index,RuleError)
                who=event['npc'];after['npcs'][who]['inner_life']=copy.deepcopy(context['npcs'][who]['inner_life'])
                after['npcs'][who]['encounter']['attraction']=context['npcs'][who]['encounter']['attraction']
        if events:
            engine._append(db,state,after,'turn-update-'+str(source_revision),
                {'status':'enrichment','action':{'kind':'freeform','text':'【人物紀錄整理】','target':''},
                 'source_revision':source_revision,'reason':'已接受故事的後續人物紀錄。','narration':'','events':events})
        db.execute("UPDATE turn_updates SET status='done',error=NULL WHERE source_revision=?",(source_revision,))


class Runner:
    def __init__(self, operation_lock, model_url, generate):
        self.operation_lock=operation_lock;self.model_url=model_url;self.generate=generate
        self.lock=threading.Lock();self.threads={}

    def kick(self,engine):
        row=latest(engine)
        if not row or row['status']!='pending':return
        key=(str(engine.path.resolve()),row['source_revision'])
        with self.lock:
            self.threads={k:v for k,v in self.threads.items() if v.is_alive()}
            if key in self.threads and self.threads[key].is_alive():return
            thread=threading.Thread(target=self._work,args=(engine,row),daemon=True,name='taleoria-character-update')
            self.threads[key]=thread;thread.start()

    def _work(self,engine,job):
        with self.operation_lock:
            try:
                state=engine.state();body=json.loads(job['body'])
                if state['revision']!=job['source_revision']:raise RuleError('故事版本已更新。')
                with engine.connect() as db:
                    source=db.execute('SELECT before_state FROM journal WHERE revision=?',(job['source_revision'],)).fetchone()
                original=json.loads(source['before_state'])
                events=self.generate(original,body['action'],body['narration'],self.model_url)
                complete(engine,job['source_revision'],events)
            except Exception as exc:
                with engine.connect() as db:
                    # Kept locally for diagnosis; status() never exposes this text.
                    db.execute("UPDATE turn_updates SET status='error',error=? WHERE source_revision=? AND status!='done'",(str(exc)[:2000],job['source_revision']))

    def retry(self,engine):
        with engine.connect() as db:
            row=db.execute("SELECT source_revision FROM turn_updates WHERE status='error' ORDER BY source_revision LIMIT 1").fetchone()
            if row:
                if engine.state()['revision']!=row['source_revision']:raise RuleError('這份人物整理已過期。')
                db.execute("UPDATE turn_updates SET status='pending',error=NULL WHERE source_revision=?",(row['source_revision'],))
        self.kick(engine)

    def join(self,timeout=5):
        for thread in list(self.threads.values()):thread.join(timeout)
