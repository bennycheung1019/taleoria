import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from kobold_rpg.campaign import new_campaign
from kobold_rpg.canon import digest
from kobold_rpg.engine import Engine, RuleError, normalize_action, check_action, validate_proposal
from kobold_rpg.model import react, without_noop_moves
from kobold_rpg.physical import attacking
from kobold_rpg.planning import source_units, source_schema, public_context, resolve_source_plan, semantic_action
from kobold_rpg.portable import export_file, validate_file
from kobold_rpg.references import audit_actor_ids
from kobold_rpg.social import model_context

RAW = '唔同佢爭論, 收起刀, 行近佢'


def classified(text, category='action', kind='freeform', target='anya', destination='', **extra):
    return {'parts': {key: category for key in source_units(text)}, 'compound':False, 'kind': kind,
            'target': target, 'destination': destination, 'ability': '', 'item': '', **extra}


class SourcePlanningTests(unittest.TestCase):
    def setUp(self):
        self.state = new_campaign(); self.state['pc']['location'] = 'pier'

    def test_literal_units_cover_all_characters_including_punctuation_and_dialect(self):
        for text in (RAW, '唔同佢爭論，收起刀，行近佢。', '唔同佢爭論\n收起刀\n行近佢',
                     'I put away my knife, move closer, and say "I won\'t argue, okay?"',
                     '唔打佢，話「我唔會打你，放心。」', '我有1.5枚錢，付1,000元。', '？',
                     '我心想「佢會唔會嬲？」然後問「你好？」'):
            with self.subTest(text=text):
                units=source_units(text)
                self.assertEqual(''.join(units.values()), text)
                self.assertTrue(all(value for value in units.values()))
        self.assertEqual(list(source_units(RAW).values()), ['唔同佢爭論,', ' 收起刀,', ' 行近佢'])
        self.assertIn('"I won\'t argue, okay?"', source_units('I say "I won\'t argue, okay?"').values())

    def test_original_three_actions_are_preserved_without_model_copying(self):
        before=copy.deepcopy(self.state)
        for text in (RAW, '唔同佢爭論，收起刀，行近佢。', '唔同佢爭論\n收起刀\n行近佢'):
            with self.subTest(text=text):
                action=resolve_source_plan(self.state,text,classified(text,item='hunting_knife'))
                self.assertEqual(action['text'],text)
                self.assertEqual(action['understanding']['actions'],[text])
                self.assertTrue(action['compound'])
                self.assertFalse(attacking(action))
                self.assertEqual(check_action(self.state,action)[0],'review')
                self.assertEqual(normalize_action(action),action)
        self.assertEqual(self.state,before)

    def test_model_can_neither_omit_a_unit_nor_supply_a_paraphrase(self):
        result=classified(RAW)
        schema=source_schema(public_context(self.state),source_units(RAW))
        self.assertEqual(schema['properties']['parts']['required'],['u0','u1','u2'])
        for parts in ({'u1':'action','u2':'action'}, {'u0':'不要和她爭論','u1':'action','u2':'action'},
                      {'u0':'action','u1':'action','u2':'action','u3':'action'}):
            with self.subTest(parts=parts),self.assertRaises(RuleError):
                resolve_source_plan(self.state,RAW,{**result,'parts':parts})

    def test_differing_output_key_order_never_reorders_the_player(self):
        result=classified(RAW)
        result['parts']=dict(reversed(list(result['parts'].items())))
        action=resolve_source_plan(self.state,RAW,result)
        self.assertEqual(action['understanding']['actions'],[RAW])

    def test_actual_dialogue_and_private_thoughts_recover_only_literal_source(self):
        text='我心想佢好可疑，收起刀，問「你叫咩名？」'
        units=source_units(text); keys=list(units)
        result=classified(text)
        result['parts']={key: ('thought' if index==0 else 'action' if index==1 else 'speech')
                         for index,key in enumerate(keys)}
        action=resolve_source_plan(self.state,text,result)
        self.assertEqual(action['understanding']['thoughts'],[units[keys[0]]])
        self.assertEqual(action['understanding']['actions'],[units[keys[1]]])
        self.assertEqual(''.join(action['understanding']['speech']),''.join(list(units.values())[2:]))
        self.assertEqual(action['text'],text)

    def test_single_model_call_contains_ids_not_retyped_source(self):
        result=classified(RAW)
        with patch('kobold_rpg.model._complete',return_value=result) as model:
            action=semantic_action(self.state,RAW,'http://local')
        model.assert_called_once()
        payload=json.loads(model.call_args.args[0][-1]['content'])
        self.assertEqual(payload['input'],RAW)
        self.assertEqual(''.join(payload['units'].values()),RAW)
        self.assertNotIn('actions',model.call_args.kwargs['response_schema']['properties'])
        self.assertEqual(action['text'],RAW)

    def test_compound_move_requires_story_and_arrival_reactions_follow_move(self):
        self.state['pc']['location']='river_street'
        text='收起刀，行近安雅'
        action=resolve_source_plan(self.state,text,classified(text,kind='travel',destination='pier'))
        self.assertEqual(action['kind'],'travel')
        self.assertEqual(check_action(self.state,action)[0],'review')
        context=model_context(self.state,action)
        self.assertIn('anya',context['npcs'])
        self.assertIn('anya',context['planned_arrival']['characters'])
        self.assertNotIn('anya',context['referenced_characters'])
        self.assertIn('anya',audit_actor_ids(self.state,action))
        moved={'type':'move','destination':'pier'}
        response={'type':'npc_update','npc':'anya','field':'stance','value':'看見對方收刀，仍留意彼此距離'}
        proposal={'outcome':'success','reason':'沿已知路線靠近，沒有省略收刀動作。',
                  'narration':'你把獵刀收好，沿河街走到渡口。安雅抬頭看你。','events':[moved,response]}
        before=copy.deepcopy(self.state)
        self.assertEqual(validate_proposal(self.state,action,proposal),proposal)
        self.assertEqual(self.state,before)
        with self.assertRaises(RuleError):
            validate_proposal(self.state,action,{**proposal,'events':[response,moved]})
        with self.assertRaises(RuleError):
            validate_proposal(self.state,action,{**proposal,'events':[moved,moved]})
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'game.sqlite3',seed=self.state)
            audit={'revision':0,'proposal_hash':digest(proposal),'result':{'supported':True,'actors':['ben','anya'],'powers':[],'issues':[]}}
            pending=engine.propose(action,proposal,0,audit=audit)
            engine.approve(pending['id'],'compound')
            self.assertEqual(engine.state()['pc']['location'],'pier')
            self.assertEqual(engine.history()[0]['action']['text'],text)
            self.assertTrue(engine.history()[0]['action']['compound'])
            self.assertTrue(engine.verify())
            validate_file(export_file(engine))

    def test_compound_without_punctuation_does_not_auto_execute_only_the_move(self):
        self.state['pc']['location']='river_street'
        text='I put away my knife and walk over to Anya'
        action=resolve_source_plan(self.state,text,classified(text,compound=True,kind='travel',destination='pier'))
        self.assertEqual(action['understanding']['actions'],[text])
        self.assertTrue(action['compound'])
        self.assertEqual(check_action(self.state,action)[0],'review')

    def test_same_place_approach_does_not_authorize_teleport_or_a_second_action(self):
        action=resolve_source_plan(self.state,RAW,classified(RAW,kind='interact',destination='pier'))
        proposal={'outcome':'success','reason':'收刀並在棚邊靠近。','narration':'安雅看著你收刀。','events':[{'type':'move','destination':'gate'}]}
        with self.assertRaises(RuleError):validate_proposal(self.state,action,proposal)
        proposal['events']=[]
        with patch('kobold_rpg.model._complete',return_value=proposal) as model:
            react(self.state,action,'http://local')
        self.assertEqual(model.call_count,1)
        self.assertIn('完整連續宣告',model.call_args.args[0][0]['content'])

    def test_same_location_assignment_is_removed_without_changing_story_or_other_events(self):
        action=resolve_source_plan(self.state,RAW,classified(RAW))
        fact={'type':'fact','text':'班收好獵刀，走近安雅。','visibility':'public'}
        proposal={'outcome':'success','reason':'在同一棚邊收刀並靠近。','narration':'安雅看見你收刀，轉過身留意你走近。',
                  'events':[fact,{'type':'move','destination':'pier'}]}
        before=copy.deepcopy(proposal)
        with patch('kobold_rpg.model._complete',return_value=proposal) as model:
            result=react(self.state,action,'http://local')
        self.assertEqual(model.call_count,1)
        self.assertEqual(result,{**proposal,'events':[fact]})
        self.assertEqual(proposal,before)
        wrong={'type':'move','destination':'gate'}
        self.assertEqual(without_noop_moves(self.state,{**proposal,'events':[wrong]})['events'],[wrong])
        malformed={'type':'move','destination':'pier','hidden':'extra'}
        self.assertEqual(without_noop_moves(self.state,{**proposal,'events':[malformed]})['events'],[malformed])


if __name__=='__main__':unittest.main()
