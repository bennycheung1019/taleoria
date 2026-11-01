"""The people page is a first-encounter index, not a live character dossier."""
import json
from pathlib import Path
import tempfile
import unittest
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine, RuleError
from kobold_rpg.gm import SCHEMA, SYSTEM, COMPACT_SYSTEM
from kobold_rpg.portable import validate_state


class FirstEncounterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.engine=Engine(Path(self.tmp.name)/'people.sqlite3',seed=new_campaign())

    def record(self,narration,changes):
        revision=self.engine.state()['revision']
        return self.engine.record_gm_reply('我和哈克聊聊。',{'narration':narration,'changes':changes},'turn-'+str(revision),revision)

    def test_first_description_stays_fixed_while_internal_state_changes(self):
        original=self.engine.public_state()['people']['hark']['description']
        result=self.record('哈克換上乾外衣，跟你說他相信你。',{'npcs':{'hark':{
            'description':'換上乾外衣的哈克。',
            'encounter':{'stance':'哈克願意信任班。'},
            'inner_life':{'current_emotions':['對班較為放心']}}}})
        self.assertEqual(result['status'],'approved')
        self.assertEqual(self.engine.state()['npcs']['hark']['description'],'換上乾外衣的哈克。')
        person=self.engine.public_state()['people']['hark']
        self.assertEqual(person['description'],original)
        self.assertNotIn('facts',person)
        self.assertNotIn('relationship',person)
        self.assertNotIn('observed_condition',person)
        self.assertNotIn('對班較為放心',json.dumps(self.engine.public_state(),ensure_ascii=False))

    def test_gm_no_longer_generates_public_card_updates(self):
        self.assertNotIn('player_view',SCHEMA['properties']['changes']['properties'])
        self.assertNotIn('player_view',SCHEMA['properties']['changes']['properties']['npcs']['additionalProperties']['properties'])
        self.assertNotIn('changes.player_view',SYSTEM)
        self.assertNotIn('changes.player_view',COMPACT_SYSTEM)

    def test_new_encounter_appears_without_rewriting_previous_description(self):
        original=self.engine.public_state()['people']['hark']['description']
        self.record('你來到渡口，遇見安雅。',{'pc':{'location':'pier'}})
        people=self.engine.public_state()['people']
        self.assertEqual(set(people),{'hark','anya'})
        self.assertEqual(people['hark']['description'],original)
        self.assertIn('整理普通繫船索',people['anya']['description'])

    def test_legacy_card_data_is_validated_but_not_shown(self):
        state=new_campaign();validate_state(state)
        state['npcs']['hark']['player_view']={'facts':{'family':{
            'text':'弟弟','evidence':'有弟弟','kind':'said','revision':'wrong'}}}
        with self.assertRaises(RuleError):validate_state(state)
        state['npcs']['hark']['player_view']['facts']['family']['revision']=0
        validate_state(state)
        engine=Engine(Path(self.tmp.name)/'legacy.sqlite3',seed=state)
        self.assertNotIn('弟弟',json.dumps(engine.public_state()['people'],ensure_ascii=False))


if __name__=='__main__':unittest.main()
