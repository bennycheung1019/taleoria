#!/usr/bin/env python3
"""Start a temporary HTTPS path to this computer's paired Taleoria engine."""
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from kobold_rpg.settings import load_settings

def main():
    executable=shutil.which('cloudflared')
    if not executable:raise SystemExit('請先安裝 Cloudflare cloudflared：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/')
    settings=load_settings(ROOT);local=f"http://127.0.0.1:{settings['port']}";owned=None;tunnel=None
    status=ROOT/'data/remote-status.json';status.parent.mkdir(parents=True,exist_ok=True)
    tunnel_config=ROOT/'data/remote-tunnel.yml'
    tunnel_config.write_text('{}\n')
    def ready():
        try:
            with urllib.request.urlopen(local+'/health',timeout=1) as r:return json.load(r).get('ok')
        except Exception:return False
    try:
        if not ready():
            owned=subprocess.Popen([sys.executable,'-B','-u',str(ROOT/'server.py')],cwd=ROOT)
            for _ in range(50):
                if ready():break
                if owned.poll() is not None:raise SystemExit('Taleoria 未能啟動。')
                time.sleep(.1)
            if not ready():raise SystemExit('Taleoria 尚未準備好。')
        tunnel=subprocess.Popen([executable,'tunnel','--config',str(tunnel_config),'--no-autoupdate','--url',local,'--protocol','http2'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        for line in tunnel.stdout:
            match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
            if match:
                value={'url':match.group(),'status':'running','temporary':True,'started_at':int(time.time())}
                temporary=status.with_suffix('.tmp');temporary.write_text(json.dumps(value));temporary.replace(status)
                print('這部電腦的遊戲網址：'+value['url'],flush=True)
                print('在 Vercel 設定填入這個網址及本機設定中的配對碼。關閉此視窗會停止遠端連線。',flush=True)
            elif 'Registered tunnel connection' in line:print('遠端連線已就緒。',flush=True)
            elif 'ERR' in line:print('連線服務：'+line.strip(),flush=True)
        return tunnel.wait()
    except KeyboardInterrupt:return 0
    finally:
        if tunnel and tunnel.poll() is None:tunnel.terminate();tunnel.wait(timeout=10)
        if status.exists():
            try:
                data=json.loads(status.read_text());data['status']='stopped';status.write_text(json.dumps(data))
            except (ValueError,OSError):pass
        if owned and owned.poll() is None:owned.terminate();owned.wait(timeout=10)
if __name__=='__main__':raise SystemExit(main())
