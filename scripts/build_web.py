#!/usr/bin/env python3
"""Allowlisted Vercel frontend only. Never ship local saves or secrets."""
import json
import shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
FILES=('app.js','connection.js','styles.css','illustrations.js','illustrations.css','favicon.svg','taleoria-mark.svg')
def build():
    output=ROOT/'web-dist';output.mkdir(exist_ok=True)
    html=(ROOT/'ui.html').read_text().replace('__SESSION_TOKEN__','HOSTED_COMPANION')
    html=html.replace('</head>','<link rel="stylesheet" href="/illustrations.css"></head>')
    html=html.replace('</body>','<script src="/illustrations.js" defer></script></body>')
    (output/'index.html').write_text(html)
    for name in FILES:shutil.copy2(ROOT/name,output/name)
    defaults=json.loads((ROOT/'web-defaults.json').read_text())
    if set(defaults)-{'companion_url','model_url'}:raise ValueError('Public defaults must contain no credentials')
    (output/'deployment.json').write_text(json.dumps(defaults))
    print('Built web-dist: static frontend, no model keys or game data')
if __name__=='__main__':build()
