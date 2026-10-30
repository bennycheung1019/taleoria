import copy
import json
from pathlib import Path
import tempfile
import unittest
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine,RuleError
from kobold_rpg.portable import export_file,validate_file,validate_state
from kobold_rpg.library import CampaignLibrary


class PlayerCardsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.engine=Engine(Path(self.tmp.name)/'cards.sqlite3',seed=new_campaign())

    def record(self,narration,changes):
        rev=self.engine.state()['revision']
        return self.engine.record_gm_reply('我和哈克聊聊。',{'narration':narration,'changes':changes},'turn-'+str(rev),rev)

    def test_learned_background_and_visible_relationship_are_public_but_private_feelings_are_not(self):
        self.record('哈克說：「我弟弟還在家裡等我。」他向你點頭道謝，語氣比剛才放鬆。',{'npcs':{'hark':{
            'inner_life':{'current_emotions':[{'feeling':'未說出口的私人情緒'}]},
            'player_view':{
                'facts':{'family':{'text':'他說家中有弟弟等他回去。','kind':'said','evidence':'我弟弟還在家裡等我'}},
                'relationship':{'text':'你們剛開始交談；他對你的關心較為放鬆。','evidence':'語氣比剛才放鬆'}}}}})
        view=self.engine.public_state();person=view['people']['hark']
        self.assertEqual(person['facts'][-1]['summary'],'他說家中有弟弟等他回去。')
        self.assertIn('較為放鬆',person['relationship'])
        self.assertNotIn('未說出口的私人情緒',json.dumps(view,ensure_ascii=False))
        self.assertNotIn('player_view',view['npcs']['hark'])
        self.assertEqual(person['interactions'],[])

    def test_information_can_be_corrected_and_relationship_changes_without_replacing_first_impression(self):
        first=self.engine.state()['npcs']['hark']['description']
        self.record('哈克說：「我弟弟還在家裡等我。」',{'npcs':{'hark':{'player_view':{'facts':{
            'family':{'text':'他說弟弟在家等他。','kind':'said','evidence':'我弟弟還在家裡等我'}}}}}})
        self.record('哈克換上乾外衣，說：「弟弟已經到親戚家了。謝謝你幫忙，我願意相信你。」',{'npcs':{'hark':{
            'description':'換上乾外衣的哈克。','player_view':{
                'facts':{'family':{'text':'他說弟弟現在由親戚照顧。','kind':'said','evidence':'弟弟已經到親戚家了'}},
                'relationship':{'text':'他表明願意相信你，對你多了一份信任。','evidence':'我願意相信你'},
                'condition':{'text':'已換上乾外衣。','evidence':'哈克換上乾外衣'}}}}})
        person=self.engine.public_state()['people']['hark']
        self.assertEqual(person['description'],first)
        summaries=[note['summary'] for note in person['facts'] if 'summary' in note]
        self.assertEqual(summaries,['他說弟弟現在由親戚照顧。'])
        self.assertIn('信任',person['relationship']);self.assertEqual(person['observed_condition'],'已換上乾外衣。')

    def test_optional_bad_notes_do_not_block_the_story_or_ordinary_state_change(self):
        narration='你走進避雨棚，把斗篷上的水抖落。'
        result=self.record(narration,{'pc':{'location':'shelter','conditions':['衣物濕透']},'npcs':{
            'hark':{'player_view':{'facts':{'secret':{'text':'他藏有未公開秘密。','kind':'observed','evidence':'不存在於故事的私人秘密'}}}},
            'anya':{'player_view':{'relationship':{'text':'她信任你。','evidence':'你走進避雨棚'}}}}})
        self.assertEqual(result['status'],'approved');self.assertEqual(result['narration'],narration)
        self.assertEqual(self.engine.state()['pc']['location'],'shelter')
        self.assertNotIn('player_view',self.engine.state()['npcs']['hark'])
        self.assertNotIn('player_view',self.engine.state()['npcs']['anya'])
        self.assertTrue(self.engine.verify())

    def test_move_and_state_changes_refresh_map_character_and_people_from_one_snapshot(self):
        self.record('你到了河街，雨斗篷已收好。',{'pc':{'location':'river_street','equipment_notes':'雨斗篷已收好。','conditions':['衣物濕冷']}})
        view=self.engine.public_state()
        self.assertEqual(view['pc']['conditions'],['衣物濕冷'])
        self.assertEqual(next(node['id'] for node in view['atlas']['nodes'] if node['current']),'river_street')
        self.assertTrue(next(node['visited'] for node in view['atlas']['nodes'] if node['id']=='gate'))
        self.assertEqual(view['people']['hark']['last_seen'],'霧橋鎮北門（Mistbridge North Gate）')
        self.record('你來到渡口，安雅把繩索收好。',{'pc':{'location':'pier'},'npcs':{'anya':{'player_view':{
            'condition':{'text':'已把繩索收好。','evidence':'安雅把繩索收好'}}}},
            'locations':{'pier':{'description':'渡口的船已繫好，安雅站在船旁。'}}})
        view=self.engine.public_state()
        self.assertEqual(set(view['people']),{'hark','anya'})
        self.assertEqual(view['people']['anya']['observed_condition'],'已把繩索收好。')
        current=next(node for node in view['atlas']['nodes'] if node['current'])
        self.assertEqual(current['id'],'pier');self.assertIn('船已繫好',current['description'])

    def test_cards_survive_portable_save_and_load(self):
        self.record('哈克說：「我家有一個弟弟。」',{'npcs':{'hark':{'player_view':{'facts':{
            'family':{'text':'他說自己有弟弟。','kind':'said','evidence':'我家有一個弟弟'}}}}}})
        payload=validate_file(export_file(self.engine))
        restored=Engine(Path(self.tmp.name)/'restored.sqlite3',seed=new_campaign())
        library=CampaignLibrary(Path(self.tmp.name)/'library',restored)
        library.import_file(payload)
        self.assertEqual(library.engine.public_state()['people'],self.engine.public_state()['people'])
        self.assertTrue(library.engine.verify())

    def test_old_saves_still_load_but_malformed_public_notes_are_rejected_as_data(self):
        state=new_campaign();validate_state(state)
        state['npcs']['hark']['player_view']={'facts':{'family':{'text':'弟弟','evidence':'有弟弟','kind':'said','revision':'wrong'}}}
        with self.assertRaises(RuleError):validate_state(state)

    def test_unchanged_notes_keep_their_original_revision(self):
        patch={'npcs':{'hark':{'player_view':{'relationship':{'text':'他願意繼續和你交談。','evidence':'我們可以繼續談談'}}}}}
        self.record('哈克說：「我們可以繼續談談。」',patch)
        self.record('哈克再說：「我們可以繼續談談。」',patch)
        self.assertEqual(self.engine.state()['npcs']['hark']['player_view']['relationship']['revision'],1)

    def test_dedicated_display_updates_never_create_a_metadata_named_character(self):
        self.record('哈克說：「我家有一個弟弟。」',{
            'npcs':{'player_view':{'npcs':{'hark':{'facts':[]}}}},
            'player_view':{'hark':{'facts':{'family':{'text':'他說自己有弟弟。','kind':'said','evidence':'我家有一個弟弟'}}}}})
        self.assertEqual(set(self.engine.state()['npcs']),{'hark','anya'})
        self.assertEqual(self.engine.public_state()['people']['hark']['facts'][-1]['summary'],'他說自己有弟弟。')


if __name__=='__main__':unittest.main()
