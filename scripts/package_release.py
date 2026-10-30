#!/usr/bin/env python3
"""Build an allowlisted clean release, optionally with a private data snapshot."""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.migrate_legacy import copy_data

ROOT_FILES = ('README.md', 'INSTALL.md', 'LICENSE', 'THIRD_PARTY.md', 'VERSION',
              '.gitignore', '.vercelignore', 'taleoria.example.json', 'taleoria.py', 'server.py',
              'Start_Taleoria.command', 'Start_Remote_Taleoria.command', 'Start_Taleoria.bat', 'start_taleoria.sh',
              'app.js', 'connection.js', 'web-defaults.json', 'vercel.json', 'ui.html', 'styles.css', 'illustrations.js', 'illustrations.css',
              'favicon.svg', 'taleoria-mark.svg')
FOLDERS = ('kobold_rpg', 'rules', 'tests', 'scripts', 'docs')


def release_files(root):
    root = Path(root)
    files = [root / p for p in ROOT_FILES]
    for name in FOLDERS:
        files.extend(p for p in (root / name).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.name != '.DS_Store'
                     and p.suffix not in {'.pyc', '.log'})
    files.extend(root / p for p in ('models/README.md', 'data/.gitkeep'))
    missing = [str(p.relative_to(root)) for p in files if not p.is_file()]
    if missing:
        raise ValueError('發佈檔案不完整：' + '、'.join(missing))
    return sorted(set(files))


def build(root=ROOT, output=None, private=False):
    root = Path(root).resolve()
    output = Path(output or root / 'dist' / ('Taleoria_Private_Backup.zip' if private else 'Taleoria.zip')).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'version': (root / 'VERSION').read_text().strip(), 'private': private,
                'created_at': datetime.now(timezone.utc).isoformat(), 'sha256': {}}
    temp_output = output.with_suffix('.zip.tmp')
    try:
        with tempfile.TemporaryDirectory(prefix='taleoria-package-') as tmp:
            stage = Path(tmp)
            if private:
                copy_data(root / 'data', stage / 'data')
            with zipfile.ZipFile(temp_output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for p in release_files(root):
                    rel = p.relative_to(root).as_posix()
                    archive.write(p, 'Taleoria/' + rel)
                    manifest['sha256'][rel] = hashlib.sha256(p.read_bytes()).hexdigest()
                if private:
                    for p in sorted((stage / 'data').rglob('*')):
                        if p.is_file() and p.name != '.gitkeep':
                            rel = p.relative_to(stage).as_posix()
                            archive.write(p, 'Taleoria/' + rel)
                            manifest['sha256'][rel] = hashlib.sha256(p.read_bytes()).hexdigest()
                    config = root / 'taleoria.local.json'
                    if config.exists():
                        from kobold_rpg.settings import load_settings
                        values = load_settings(root)
                        values['db'] = Path(values['db']).relative_to(root).as_posix()
                        config_bytes = json.dumps(values, ensure_ascii=False, indent=2).encode()
                        archive.writestr('Taleoria/taleoria.local.json', config_bytes)
                        manifest['sha256']['taleoria.local.json'] = hashlib.sha256(config_bytes).hexdigest()
                    archive.writestr('Taleoria/PRIVATE_BACKUP.txt',
                                     '私人搬機備份：包含遊戲紀錄、世界私密資料與圖片。請勿公開上傳。\n')
                archive.writestr('Taleoria/RELEASE_MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(temp_output, output)
    finally:
        temp_output.unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private', action='store_true', help='加入自己的 data；請先停止 Taleoria')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        output = build(output=args.output, private=args.private)
    except (OSError, ValueError) as exc:
        parser.exit(1, '打包未完成：' + str(exc) + '\n')
    print(('私人備份：' if args.private else '乾淨安裝包：') + str(output))


if __name__ == '__main__':
    main()
