"""Authenticated, origin-bound browser access to the local RPG service.

The tunnel may reach this handler; it never receives the local HTML token.
KoboldCpp and Draw Things continue listening only on the local computer.
"""
import hmac
import json
import os
import secrets
import urllib.parse
from pathlib import Path


def origin(value):
    try:
        url=urllib.parse.urlsplit(value)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.path not in ('','/') or url.query or url.fragment:return None
        return f'https://{url.netloc}'
    except (ValueError,TypeError):return None


def load_config(path):
    path=Path(path)
    if path.exists():data=json.loads(path.read_text())
    else:
        data={'key':secrets.token_urlsafe(32),'allowed_origins':[]}
        path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as file:json.dump(data,file,indent=2)
    if not isinstance(data.get('key'),str) or len(data['key'])<32:raise ValueError('Companion 配對碼無效。')
    if not isinstance(data.get('allowed_origins'),list) or any(origin(value)!=value for value in data['allowed_origins']):raise ValueError('Companion 只接受完整 HTTPS 網站來源。')
    return data


def with_companion(base,token,config,config_path=None):
    key=config['key']
    class Handler(base):
        def allowed(self):return set(config.get('allowed_origins',[]))
        def local_request(self):
            try:
                host=urllib.parse.urlsplit('http://'+self.headers.get('Host','')).hostname
                request_origin=self.headers.get('Origin')
                return (host in ('localhost','127.0.0.1','::1') and not self.headers.get('X-Forwarded-Host')
                    and not self.headers.get('CF-Connecting-IP') and (not request_origin or request_origin=='http://'+self.headers.get('Host','')))
            except ValueError:return False

        def end_headers(self):
            request_origin=self.headers.get('Origin')
            if request_origin in self.allowed():
                self.send_header('Access-Control-Allow-Origin',request_origin)
                self.send_header('Vary','Origin')
                self.send_header('Access-Control-Allow-Private-Network','true')
            super().end_headers()

        def do_OPTIONS(self):
            if self.headers.get('Origin') not in self.allowed():
                self.send(403,{'error':'這個網站尚未在本機配對。'});return
            headers={v.strip().lower() for v in self.headers.get('Access-Control-Request-Headers','').split(',') if v.strip()}
            if not headers <= {'content-type','x-rpg-token','x-rpg-session','x-taleoria-key','prefer'}:
                self.send(403,{'error':'不支援的連線欄位。'});return
            if self.headers.get('Access-Control-Request-Method') not in ('GET','POST'):
                self.send(405,{'error':'不支援的操作。'});return
            self.send_response(204)
            self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers','Content-Type, X-RPG-Token, X-RPG-Session, X-Taleoria-Key, Prefer')
            self.send_header('Access-Control-Max-Age','600');self.send_header('Content-Length','0');self.end_headers()

        def authorize(self):
            if self.local_request():return True
            request_origin=self.headers.get('Origin')
            if request_origin and request_origin not in self.allowed():
                self.send(403,{'error':'這個網站尚未在本機配對。'});return False
            supplied=self.headers.get('X-Taleoria-Key','')
            if not hmac.compare_digest(supplied,key):
                self.send(401,{'error':'請在設定輸入這部電腦的配對碼。'});return False
            path=urllib.parse.urlsplit(self.path).path
            if not path.startswith('/api/') or path in ('/api/export','/api/gm/npcs','/api/gm/canon','/api/companion/pairing'):
                self.send(404,{'error':'請從 Taleoria 網站遊玩。'});return False
            if 'X-RPG-Token' in self.headers:del self.headers['X-RPG-Token']
            self.headers['X-RPG-Token']=token
            return True

        def do_GET(self):
            if urllib.parse.urlsplit(self.path).path=='/api/companion/pairing' and self.local_request():
                if self.headers.get('X-RPG-Token')!=token:self.send(403,{'error':'請從本機設定查看配對碼。'});return
                remote={}
                if config_path:
                    try:remote=json.loads((Path(config_path).parent/'remote-status.json').read_text())
                    except (OSError,ValueError):pass
                self.send(200,{'key':key,'allowed_origins':list(self.allowed()),'remote':remote});return
            if self.authorize():return super().do_GET()

        def do_POST(self):
            if urllib.parse.urlsplit(self.path).path=='/api/companion/pairing' and self.local_request():
                if self.headers.get('X-RPG-Token')!=token:self.send(403,{'error':'請從本機設定變更配對。'});return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=4096:raise ValueError()
                    data=json.loads(self.rfile.read(size));value=origin(data.get('website'))
                    if not value:raise ValueError()
                    updated={'key':key,'allowed_origins':sorted(self.allowed()|{value})}
                    if config_path:
                        temporary=Path(config_path).with_suffix('.tmp')
                        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                        with os.fdopen(fd,'w') as file:json.dump(updated,file,indent=2)
                        temporary.replace(config_path)
                    config.update(updated)
                    self.send(200,{'allowed_origins':updated['allowed_origins']})
                except (ValueError,AttributeError,TypeError):self.send(400,{'error':'請填入完整的 HTTPS Taleoria 網址。'})
                return
            if self.authorize():return super().do_POST()
    return Handler
