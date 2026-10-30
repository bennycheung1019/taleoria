"""Private, bounded checkpoints of unfinished creation; never a campaign save."""
import hashlib
import json
import os
from pathlib import Path
from .engine import RuleError
from .portable import validate_state


class DraftCheckpoint:
    def __init__(self, folder, preferences, model_url):
        self.folder=Path(folder) if folder else None
        key=json.dumps(['progressive-1',preferences,model_url],ensure_ascii=False,sort_keys=True)
        self.key=hashlib.sha256(key.encode()).hexdigest()
        self.path=self.folder/(self.key+'.json') if self.folder else None

    def load(self):
        if not self.path or not self.path.exists():return None
        try:
            if self.path.stat().st_size>2*1024*1024:return None
            value=json.loads(self.path.read_text())
            if value.get('checkpoint')!=self.key:return None
            candidate=value['candidate'];validate_state(candidate['seed'])
            if not all(key in candidate for key in ('plan','preferences','seed')):return None
            return candidate
        except (OSError,ValueError,KeyError,TypeError,RuleError):return None

    def save(self,candidate):
        if not self.path:return
        self.folder.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'checkpoint':self.key,'candidate':candidate},ensure_ascii=False))
        os.chmod(temporary,0o600);os.replace(temporary,self.path)
        # Only disposable, unconfirmed checkpoints are evicted. Canonical worlds
        # and their history are stored elsewhere and never touched here.
        old=sorted(self.folder.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        for path in old[8:]:path.unlink(missing_ok=True)

    def complete(self):
        if self.path:self.path.unlink(missing_ok=True)
