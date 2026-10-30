"""Bounded, session-scoped results that outlive the browser's HTTP connection."""
import copy
import json
import threading
from .engine import RuleError


class JobStore:
    def __init__(self, capacity=64):
        self.lock = threading.RLock()
        self.jobs = {}
        self.capacity = capacity

    def start(self, path, body, execute):
        request = body.get('request_id')
        if not isinstance(request, str) or not 1 <= len(request) <= 120:
            raise RuleError('需要有效的行動識別。')
        key = (body.get('session_id', ''), request)
        fingerprint = json.dumps([path, body], sort_keys=True, ensure_ascii=False)
        with self.lock:
            if key in self.jobs:
                if self.jobs[key]['fingerprint'] != fingerprint:
                    raise RuleError('同一行動識別不能改成另一項操作。')
                return
            if any(job['status'] == 'running' for job in self.jobs.values()):
                raise RuleError('已有生成正在處理，請等它完成後再送出。')
            if len(self.jobs) >= self.capacity:
                self.jobs.pop(next(iter(self.jobs)))
            job = {'path': path, 'status': 'running', 'fingerprint': fingerprint}
            self.jobs[key] = job

            def run():
                try:
                    code, result = execute()
                except Exception:
                    code, result = 500, {'error': '操作未完成，請重新整理確認故事進度。'}
                with self.lock:
                    job.update(status='done' if code == 200 else 'error', code=code, result=result)

            thread = threading.Thread(target=run, daemon=True)
            job['thread'] = thread
            thread.start()

    def snapshot(self, session, request):
        with self.lock:
            job = self.jobs.get((session, request))
            if job is None:
                return None
            return copy.deepcopy({key: job[key] for key in ('path', 'status', 'code', 'result') if key in job})

    def join(self):
        with self.lock:
            threads = [job['thread'] for job in self.jobs.values()]
        for thread in threads:
            thread.join()
