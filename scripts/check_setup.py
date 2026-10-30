#!/usr/bin/env python3
"""Read-only checks. Does not generate text/images or change game data."""
import json
import platform
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from kobold_rpg.settings import load_settings
from kobold_rpg.illustrations import http_json


def main():
    print('Taleoria 安裝檢查 ·', platform.system(), platform.machine())
    print('Python:', platform.python_version(), '· 專案:', ROOT)
    try:
        values = load_settings(ROOT)
    except (ValueError, OSError) as exc:
        print('設定錯誤：', exc)
        return 1
    print('遊戲網址:', f"http://127.0.0.1:{values['port']}")
    print('資料庫:', values['db'])
    try:
        data = http_json(values['model_url'] + '/api/v1/model', timeout=3)
        print('KoboldCpp 已連接:', data.get('result', '未知模型'))
    except Exception:
        print('KoboldCpp 未連接:', values['model_url'], '· 請載入 GGUF 並啟動服務。')
    path = Path(values['db'])
    library = path.parent / ('library' if path == ROOT / 'data/mistbridge.sqlite3' else path.stem + '-library')
    endpoint = 'http://127.0.0.1:7860'
    config_db = library / 'illustrations/illustrations.sqlite3'
    if config_db.is_file():
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(config_db.as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute('SELECT body FROM config WHERE id=1').fetchone()
        if row:
            endpoint = json.loads(row[0]).get('endpoint', endpoint)
    try:
        data = http_json(endpoint + '/sdapi/v1/options', timeout=3)
        print('Draw Things 已連接:', data.get('sd_model_checkpoint', '已載入'))
    except Exception:
        print('Draw Things 未連接:', endpoint, '· 不影響純文字遊玩。')
    print('本檢查沒有推進故事或生成圖片。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
