#!/usr/bin/env python3
"""Copy an old project's data without modifying it; rebase legacy save indexes."""
import argparse
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def signature(folder):
    return {p.relative_to(folder).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in folder.rglob('*') if p.is_file() and p.name != '.DS_Store'}


def copy_data(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir():
        raise ValueError('找不到來源 data 資料夾。')
    if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('來源與目的資料夾不能互相包含。')
    if destination.exists() and any(p.name != '.gitkeep' for p in destination.iterdir()):
        raise ValueError('目的 data 已有進度；請選擇空資料夾，避免覆蓋。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = signature(source)
    with tempfile.TemporaryDirectory(prefix='.taleoria-migration-', dir=destination.parent) as tmp:
        stage = Path(tmp) / 'data'
        stage.mkdir()
        for rel in before:
            p = source / rel
            if p.is_symlink():
                raise ValueError('data 含符號連結，請先改成普通檔案。')
            if p.name.endswith(('-wal', '-shm', '-journal')):
                continue
            out = stage / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            if p.suffix == '.sqlite3':
                with closing(sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)) as src:
                    with closing(sqlite3.connect(out)) as dst:
                        src.backup(dst)
                        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                            raise ValueError('資料庫完整性檢查未通過：' + rel)
            else:
                shutil.copy2(p, out)
        # All indexed files must belong to this copied data tree, never the old Mac.
        for index in stage.rglob('index.json'):
            data = json.loads(index.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or not {'campaigns', 'saves'} <= data.keys():
                continue
            old_root = source / index.parent.relative_to(stage)
            for group in ('campaigns', 'saves'):
                for row in data[group].values():
                    p = Path(row['path'])
                    p = (old_root / p).resolve()
                    if not p.is_relative_to(source) or not p.is_file():
                        raise ValueError('存檔清單指向 data 外或遺失的檔案。')
                    copied = stage / p.relative_to(source)
                    if not copied.is_file():
                        raise ValueError('複製的存檔不完整。')
                    row['path'] = Path(os.path.relpath(copied, index.parent)).as_posix()
            index.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        if signature(source) != before:
            raise ValueError('來源進度在複製期間改變；請停止舊 Taleoria 後再試。目的資料未改動。')
        (stage / '.gitkeep').touch()
        # No writes outside destination. The old copy remains an independent backup.
        if destination.exists():
            (destination / '.gitkeep').unlink(missing_ok=True)
            destination.rmdir()
        stage.replace(destination)
    return len(before)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('old_project', type=Path)
    parser.add_argument('--destination', type=Path, default=ROOT / 'data')
    args = parser.parse_args()
    try:
        count = copy_data(args.old_project / 'data', args.destination)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, '未搬入進度：' + str(exc) + '\n')
    print(f'已複製 {count} 個資料檔並改用可攜路徑。舊專案保持原狀。')


if __name__ == '__main__':
    main()
