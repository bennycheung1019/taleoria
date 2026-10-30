#!/usr/bin/env python3
"""Apply the illustration extension without overwriting concurrent context fixes."""
import argparse
import ast
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

FILES = ('kobold_rpg/illustrations.py', 'illustrations.js', 'illustrations.css', 'scripts/legacy_images.py',
         'tests/test_illustrations.py', 'tests/test_illustrations_ui.cjs', 'docs/IMAGE_GENERATION.md')


def patched_server(text):
    tree = ast.parse(text)
    function = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'make_handler'), None)
    if function is None:
        raise ValueError('找不到 make_handler；請先檢查專案版本。')
    if 'return with_illustrations(Handler, engine, model_url, token, library, operation_lock)' not in text:
        returns = [n for n in function.body if isinstance(n, ast.Return) and isinstance(n.value, ast.Name) and n.value.id == 'Handler']
        if len(returns) != 1:
            raise ValueError('server.py 的掛接位置已變動，未套用任何修改。')
        lines = text.splitlines(keepends=True)
        item = returns[0]
        lines[item.lineno-1:item.end_lineno] = ['    return with_illustrations(Handler, engine, model_url, token, library, operation_lock)\n']
        text = ''.join(lines)
    import_line = 'from kobold_rpg.illustrations import with_illustrations\n'
    if import_line not in text:
        anchor = 'from pathlib import Path\n'
        if text.count(anchor) != 1:
            raise ValueError('找不到匯入位置，未套用任何修改。')
        text = text.replace(anchor, anchor + import_line, 1)
    cleanup = '        server.RequestHandlerClass.background.join()\n'
    if 'server.RequestHandlerClass.illustrations.join()' not in text:
        if text.count(cleanup) != 1:
            raise ValueError('找不到服務結束位置，未套用任何修改。')
        text = text.replace(cleanup, cleanup + '        server.RequestHandlerClass.illustrations.join()\n', 1)
    compile(text, 'server.py', 'exec')
    return text


def install(target, source=None, dry_run=False):
    target = Path(target).expanduser().resolve()
    source = Path(source or Path(__file__).resolve().parent.parent)
    server = target / 'server.py'
    if not server.is_file() or not (target / 'kobold_rpg/engine.py').is_file():
        raise ValueError('請選擇含 server.py 和 kobold_rpg 的 Taleoria 專案資料夾。')
    before = server.read_bytes()
    updated = patched_server(before.decode()).encode()
    writes = {name: (source / name).read_bytes() for name in FILES}
    writes['server.py'] = updated
    writes = {name: data for name, data in writes.items()
              if not (target/name).exists() or (target/name).read_bytes() != data}
    if not writes:
        print('插畫整合已是最新版本，不需要修改。')
        return
    print('目標：' + str(target))
    print('更新：' + '、'.join(writes))
    print('保留現有 context／對話程式、遊戲資料與存檔。')
    if dry_run:
        print('預檢通過，沒有寫入目標資料夾。')
        return
    # Re-read immediately before applying; never replace a newly edited server.
    if server.read_bytes() != before:
        raise ValueError('server.py 正在被另一個工作修改；請稍後重試。')
    backup = target / 'image-update-backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup.mkdir(parents=True)
    missing = []
    for name in writes:
        old = target / name
        if old.exists():
            dest = backup / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, dest)
        else:
            missing.append(name)
    (backup / 'new-files.txt').write_text('\n'.join(missing))
    installed = []
    try:
        for name, data in writes.items():
            dest = target / name
            if name == 'server.py' and dest.read_bytes() != before:
                raise ValueError('server.py 在安裝期間被更新，已停止並還原本次新增檔案。')
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as tmp:
                temp = Path(tmp.name)
                tmp.write(data)
            temp.replace(dest)
            installed.append(name)
    except Exception:
        for name in reversed(installed):
            saved = backup / name
            if saved.exists():
                shutil.copy2(saved, target / name)
            elif name in missing:
                (target / name).unlink(missing_ok=True)
        raise
    print('安裝完成。原始檔備份：' + str(backup))
    print('請在原本運行 Taleoria 的終端機按 Ctrl+C，再用原本方式啟動。')
    print('開啟 Taleoria → 遊戲設定 → 插畫，按「儲存並測試連線」。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', help='要更新的 Taleoria 專案資料夾')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        install(args.target, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        parser.exit(1, '未完成安裝：' + str(exc) + '\n')
