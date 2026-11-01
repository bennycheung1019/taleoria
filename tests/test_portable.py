import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from kobold_rpg.engine import Engine, RuleError, canonical
from kobold_rpg.campaign import new_campaign
from kobold_rpg.library import CampaignLibrary
from kobold_rpg.portable import export_file, validate_file


def checksum(payload):
    payload['checksum']=hashlib.sha256(canonical({k:v for k,v in payload.items() if k!='checksum'}).encode()).hexdigest()


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.original=Engine(Path(self.tmp.name)/'world.db',seed=new_campaign())
        self.original.record_gm_reply('環顧四周',{'narration':'門外下著雨。','changes':{}},'look',0)
        self.library=CampaignLibrary(Path(self.tmp.name)/'library',self.original)

    def test_file_restores_full_world_history_and_known_people(self):
        data=export_file(self.original);before=self.original.state();old_session=self.library.session_id
        self.library.import_file(data)
        self.assertEqual(self.library.engine.state(),before)
        self.assertEqual(self.library.engine.history(),self.original.history())
        self.assertEqual(self.library.engine.public_state()['people'],self.original.public_state()['people'])
        self.assertNotEqual(self.library.engine.path,self.original.path)
        self.assertNotEqual(self.library.session_id,old_session)
        self.library.engine.record_gm_reply('再看看',{'narration':'仍在下雨。','changes':{}},'again',1)
        self.assertEqual(self.original.state()['revision'],1)
        self.assertEqual(self.library.engine.state()['revision'],2)

    def test_corrupt_file_is_rejected_without_creating_or_switching(self):
        data=export_file(self.original);data['state']['pc']['name']='損壞內容'
        before=self.library.engine.state()
        with self.assertRaises(RuleError):self.library.import_file(data)
        self.assertEqual(self.library.engine.state(),before)
        self.assertEqual(list((self.library.root/'campaigns').glob('*.sqlite3')),[])

    def test_even_recomputed_outer_checksum_cannot_hide_broken_event_chain(self):
        data=export_file(self.original);data['journal'][0]['body']='{"narration":"被改寫"}';checksum(data)
        with self.assertRaises(RuleError):validate_file(data)

    def test_missing_location_or_character_fields_are_rejected(self):
        for field in ['locations','npcs']:
            data=export_file(self.original);data['state'][field]={};checksum(data)
            with self.assertRaises(RuleError):validate_file(data)

    def test_old_reading_export_is_not_misrepresented_as_complete_save(self):
        with self.assertRaises(RuleError):validate_file({'format':'kobold-rpg-0.3','state':self.original.state()})

    def test_save_contains_no_executable_sql_or_pending_proposal_import_path(self):
        data=export_file(self.original)
        self.assertEqual(set(data),{'format','version','created_at','state','journal','checksum'})
        self.assertNotIn('proposals',data)


if __name__=='__main__':unittest.main()
