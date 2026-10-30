"""Portable launch settings. Relative files are rooted at the project folder."""
import json
from pathlib import Path
from .illustrations import endpoint_url

DEFAULTS = {'port': 8787, 'db': 'data/taleoria.sqlite3',
            'model_url': 'http://127.0.0.1:5001'}


def load_settings(root, config=None):
    root = Path(root).resolve()
    path = Path(config) if config else root / 'taleoria.local.json'
    if not path.is_absolute():
        path = root / path
    values = dict(DEFAULTS)
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) - set(DEFAULTS):
            raise ValueError('設定只接受 port、db、model_url。請參照 taleoria.example.json。')
        values.update(data)
    elif config:
        raise ValueError('找不到指定的 Taleoria 設定檔。')
    return validate_settings(root, values)


def validate_settings(root, values):
    values = dict(values)
    if type(values['port']) is not int or not 1 <= values['port'] <= 65535:
        raise ValueError('Taleoria port 必須介於 1 至 65535。')
    values['model_url'] = endpoint_url(values['model_url'])
    if not isinstance(values['db'], str) or not values['db'].strip():
        raise ValueError('db 必須是遊戲資料庫的檔案路徑。')
    path = Path(values['db'])
    values['db'] = str((Path(root) / path).resolve())
    return values
