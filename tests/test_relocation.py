"""Real file moves and clean/private archives, without requiring a model or sockets."""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine, RuleError
from kobold_rpg.library import CampaignLibrary
from kobold_rpg.settings import load_settings
from scripts.migrate_legacy import copy_data, signature
from scripts.package_release import ROOT, build, release_files


class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.old = self.base / 'Old computer' / 'Kobold RPG' / 'data'
        self.old.mkdir(parents=True)
        self.engine = Engine(self.old / 'mistbridge.sqlite3', seed=new_campaign())
        self.library = CampaignLibrary(self.old / 'library', self.engine)
        self.engine.record_gm_reply('我查看城門。',{'narration':'城門仍半掩。','changes':{}},'relocate-observe',0)
        self.saved = self.library.save('搬機前')
        self.library.load('save', self.saved['id'])
        art = self.library.root / 'illustrations'
        art.mkdir()
        (art / 'fixture.png').write_bytes(b'PNG-backup-fixture')

    def test_renaming_whole_folder_restores_active_branch_and_saved_game(self):
        expected = self.library.engine.state()
        journal = self.library.engine.history()
        disk = json.loads(self.library.index_path.read_text())
        self.assertTrue(all(not Path(row['path']).is_absolute()
                            for group in disk.values() for row in group.values()))
        moved = self.base / 'Another user' / 'Renamed Taleoria'
        moved.parent.mkdir()
        shutil.move(str(self.old.parent), moved)
        restored = CampaignLibrary(moved / 'data/library', Engine(moved / 'data/mistbridge.sqlite3'))
        self.assertEqual(restored.engine.state(), expected)
        self.assertEqual(restored.engine.history(), journal)
        self.assertTrue(restored.engine.verify())
        self.assertEqual((restored.root / 'illustrations/fixture.png').read_bytes(), b'PNG-backup-fixture')
        self.assertEqual(sum(r['active'] for r in restored.list()['campaigns']), 1)
        restored.load('save', self.saved['id'])
        self.assertEqual(restored.engine.state(), expected)

    def test_legacy_absolute_index_is_copied_and_rebased_without_source_changes(self):
        # Recreate the original release's absolute on-disk index.
        self.library.index_path.write_text(json.dumps(self.library.index))
        before = signature(self.old)
        new_data = self.base / 'Taleoria/data'
        count = copy_data(self.old, new_data)
        self.assertGreater(count, 2)
        self.assertEqual(signature(self.old), before)
        shutil.rmtree(self.old)  # Prove the copied library never falls back to the source.
        restored = CampaignLibrary(new_data / 'library', Engine(new_data / 'mistbridge.sqlite3'))
        self.assertEqual(restored.engine.state()['revision'], 1)
        self.assertTrue(restored.engine.verify())
        restored.load('save', self.saved['id'])
        self.assertEqual(restored.engine.state()['revision'], 1)

    def test_destination_data_is_not_overwritten(self):
        destination = self.base / 'existing-data'
        destination.mkdir()
        marker = destination / 'keep.txt'
        marker.write_text('private progress')
        with self.assertRaises(ValueError):
            copy_data(self.old, destination)
        self.assertEqual(marker.read_text(), 'private progress')

    def test_legacy_index_outside_data_is_rejected_before_publish(self):
        index = self.library.index
        next(iter(index['campaigns'].values()))['path'] = str(self.base / 'external.sqlite3')
        self.library.index_path.write_text(json.dumps(index))
        destination = self.base / 'new-data'
        with self.assertRaises(ValueError):
            copy_data(self.old, destination)
        self.assertFalse(destination.exists())

    def test_relative_settings_resolve_from_project_even_when_working_directory_differs(self):
        root = self.base / 'Taleoria'
        root.mkdir()
        (root / 'taleoria.local.json').write_text(json.dumps({'db': 'data/custom.sqlite3',
            'port': 8899, 'model_url': 'http://127.0.0.1:5002/'}))
        values = load_settings(root)
        self.assertEqual(values['db'], str((root / 'data/custom.sqlite3').resolve()))
        self.assertEqual(values['model_url'], 'http://127.0.0.1:5002')
        self.assertEqual(values['port'], 8899)

    def test_invalid_launch_settings_are_rejected(self):
        root = self.base / 'settings'
        root.mkdir()
        for data in ({'port': 0}, {'port': True}, {'model_url': 'https://example.com'},
                     {'model_url': 'http://localhost:5001/v1'}, {'unknown_key': 1}, []):
            with self.subTest(data=data):
                (root / 'taleoria.local.json').write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    load_settings(root)

    def test_clean_archive_excludes_all_player_data_and_has_valid_hashes(self):
        archive = build(ROOT, self.base / 'clean.zip')
        with zipfile.ZipFile(archive) as release:
            names = release.namelist()
            self.assertEqual([x for x in names if x.startswith('Taleoria/data/')], ['Taleoria/data/.gitkeep'])
            self.assertFalse(any(x.endswith(('.gguf', '.safetensors', '.sqlite3', '.rpgsave')) for x in names))
            self.assertNotIn('Taleoria/taleoria.local.json', names)
            self.assertFalse(any('/archive/' in x or '/work/' in x for x in names))
            manifest = json.loads(release.read('Taleoria/RELEASE_MANIFEST.json'))
            self.assertFalse(manifest['private'])
            for name, digest in manifest['sha256'].items():
                self.assertEqual(hashlib.sha256(release.read('Taleoria/' + name)).hexdigest(), digest)
            launcher = release.getinfo('Taleoria/Start_Taleoria.command')
            self.assertTrue(launcher.external_attr >> 16 & 0o111)

    def test_private_archive_restores_data_and_images_on_a_different_path(self):
        root = self.base / 'source-release'
        root.mkdir()
        for p in release_files(ROOT):
            dest = root / p.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
        # Replace empty data with our isolated fixture.
        copy_data(self.old, root / 'data')
        (root / 'taleoria.local.json').write_text(json.dumps({'db': 'data/mistbridge.sqlite3'}))
        archive = build(root, self.base / 'private.zip', private=True)
        restored_root = self.base / 'new-computer'
        with zipfile.ZipFile(archive) as release:
            release.extractall(restored_root)
            self.assertTrue(json.loads(release.read('Taleoria/RELEASE_MANIFEST.json'))['private'])
        restored_root /= 'Taleoria'
        values = load_settings(restored_root)
        restored = CampaignLibrary(restored_root / 'data/library', Engine(values['db']))
        self.assertEqual(restored.engine.state(), self.library.engine.state())
        self.assertEqual(restored.engine.history(), self.library.engine.history())
        self.assertEqual((restored.root / 'illustrations/fixture.png').read_bytes(), b'PNG-backup-fixture')


if __name__ == '__main__':
    unittest.main()
