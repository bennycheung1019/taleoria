"""Request-scoped progress. Estimates never expose generated/private text."""
import contextvars
import threading
import time
from contextlib import contextmanager

active = contextvars.ContextVar('rpg_progress', default=None)
label = contextvars.ContextVar('rpg_stage', default='準備故事')


@contextmanager
def stage(name):
    token=label.set(name)
    try: yield
    finally: label.reset(token)


class Progress:
    def __init__(self, steps):
        self.lock=threading.RLock();self.started=time.monotonic();self.steps=steps
        self.calls=0;self.completed=0;self.fragments=0;self.maximum=1
        self.phase='準備中';self.title='準備故事';self.status='running';self.high=0
        self.call_started=self.started;self.prompt_seconds=None;self.speed=None

    def begin(self, maximum, messages, perf):
        with self.lock:
            self.calls+=1;self.steps=max(self.steps,self.calls)
            self.title=label.get();self.phase='處理提示';self.fragments=0;self.maximum=maximum
            self.call_started=time.monotonic()
            speed=perf.get('last_eval_speed');process=perf.get('last_process_speed')
            self.speed=speed if isinstance(speed,(int,float)) and speed>0 else None
            # Message characters approximate input length; chat-template and cache
            # effects are unknown, so this is explicitly an estimate in the UI.
            self.prompt_seconds=max(.1,sum(len(m['content']) for m in messages)/2.5/process) if isinstance(process,(int,float)) and process>0 else None

    def fragment(self):
        with self.lock:self.phase='生成內容';self.fragments+=1

    def call_done(self):
        with self.lock:self.completed=self.calls;self.phase='檢查結果'

    def finish(self, success):
        with self.lock:self.status='done' if success else 'error';self.phase='已完成' if success else '未完成'

    def snapshot(self):
        with self.lock:
            elapsed=time.monotonic()-self.started;call_elapsed=time.monotonic()-self.call_started
            fraction=0;remaining=None
            if self.calls>self.completed:
                if self.phase=='處理提示' and self.prompt_seconds:
                    fraction=.15*min(.95,call_elapsed/self.prompt_seconds)
                elif self.phase=='生成內容':fraction=.15+.85*min(.99,self.fragments/self.maximum)
                if self.speed:
                    remaining=max(0,self.maximum-self.fragments)/self.speed
                    if self.phase=='處理提示' and self.prompt_seconds:remaining+=max(0,self.prompt_seconds-call_elapsed)
            percent=min(99,int(100*(self.completed+fraction)/self.steps))
            self.high=max(self.high,percent)
            return {'status':self.status,'stage':self.title,'phase':self.phase,
                    'percent':100 if self.status=='done' else self.high,'estimated':self.status!='done',
                    'elapsed_seconds':round(elapsed),'stage_remaining_upper_seconds':round(remaining) if remaining is not None else None}


class ProgressStore:
    def __init__(self):self.lock=threading.Lock();self.jobs={}
    def start(self, session, request, steps):
        with self.lock:
            if len(self.jobs)>=64:
                finished=[k for k,v in self.jobs.items() if v.status!='running']
                if finished:self.jobs.pop(finished[0])
            job=Progress(steps);self.jobs[(session,request)]=job;return job
    def snapshot(self,session,request):
        with self.lock:job=self.jobs.get((session,request))
        return job.snapshot() if job else {'status':'waiting','stage':'準備中','phase':'等待處理','percent':0,'estimated':True,'elapsed_seconds':0,'stage_remaining_upper_seconds':None}
