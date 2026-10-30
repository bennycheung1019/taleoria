import copy,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine,RuleError,check_action,normalize_action,validate_proposal
from kobold_rpg.play import interpret
from kobold_rpg.navigation import movement
from kobold_rpg.model import parse_proposal,InvalidJSONError,react,_complete
from kobold_rpg.world_schema import proposal_schema


class NavigationProtocolTests(unittest.TestCase):
    def setUp(self):
        self.state=new_campaign();self.state['pc']['location']='river_street'

    def test_shared_movement_resolution_covers_named_people_places_and_languages(self):
        for text in ('get close to anya','get closer to anya','I get closer to Anya.','move closer to Anya',
                     'get  close   to Anya','Get close to Anya.','please get close to Anya',
                     'get a bit closer to Anya','come close to Anya','go close to Anya',
                     'approach Anya','walk up to Anya','go over to Anya','walk to Anya',
                     'head to Anya','go to Anya','走近安雅','我靠近安雅。','接近安雅','走向安雅',
                     'go to Ferry Pier','walk to Ferry Pier','前往渡口','我走到渡口。'):
            with self.subTest(text=text):
                resolver=Mock(side_effect=AssertionError('plain movement needs no model'))
                action=interpret(self.state,text,resolver=resolver)
                self.assertEqual(action['text'],text)
                self.assertEqual(action['kind'],'travel')
                self.assertEqual(action['destination'],'pier')
                self.assertEqual(action['target'],'')
                self.assertEqual(check_action(self.state,action)[0],'routine')
                resolver.assert_not_called()

    def test_full_observe_approach_observe_speak_sequence_preserves_world_and_person(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'world.sqlite3',seed=self.state)
            before=copy.deepcopy(engine.state()['npcs']['anya'])
            engine.submit(interpret(engine.state(),'check out Anya'),'look',0)
            action=interpret(engine.state(),'get closer to anya')
            result=engine.submit(action,'closer',1)
            self.assertEqual(result['status'],'routine')
            self.assertEqual(engine.state()['pc']['location'],'pier')
            self.assertEqual(engine.state()['npcs']['anya'],before)
            self.assertIn('安雅',result['narration'])
            engine.submit(interpret(engine.state(),'look at Anya'),'look-near',2)
            dialogue=interpret(engine.state(),'why are you here?')
            self.assertEqual(dialogue['target'],'anya');self.assertEqual(dialogue['kind'],'speak')
            self.assertEqual(check_action(engine.state(),dialogue)[0],'review')
            self.assertTrue(engine.verify())

    def test_close_and_closer_share_the_same_parser_for_all_motion_verbs(self):
        for verb in ('get','move','come','go'):
            for adjective in ('close','closer'):
                for modifier in ('','a bit ','a little ','slightly '):
                    text=f'{verb} {modifier}{adjective} to anya'
                    with self.subTest(text=text):
                        action=interpret(self.state,text,resolver=Mock(side_effect=AssertionError('no understanding model')))
                        self.assertEqual(action['kind'],'travel');self.assertEqual(action['destination'],'pier')
                        self.assertEqual(action['text'],text)

    def test_nearby_person_is_an_interaction_not_a_same_location_teleport(self):
        self.state['pc']['location']='pier'
        action=interpret(self.state,'get closer to Anya')
        self.assertEqual(action['kind'],'interact');self.assertEqual(action['target'],'anya')
        self.assertEqual(check_action(self.state,action)[0],'review')

    def test_obstructed_route_requires_review_and_does_not_move_automatically(self):
        self.state['locations']['river_street']['exits']['pier']['clear']=False
        action=interpret(self.state,'approach Anya')
        self.assertEqual(action['kind'],'travel')
        self.assertEqual(check_action(self.state,action)[0],'review')

    def test_hidden_or_unlocated_person_does_not_reveal_private_destination(self):
        self.state['locations']['river_street']['description']='雨落在空蕩的河街。'
        self.assertIsNone(movement(self.state,'get closer to Anya'))
        self.state['npcs']['anya']['known']=False
        self.assertIsNone(movement(self.state,'go to Anya'))
        self.assertIsNone(movement(self.state,'go to unknown palace'))

    def test_old_public_location_does_not_follow_private_npc_movement(self):
        self.state['npcs']['anya']['location']='gate'
        self.assertEqual(movement(self.state,'get closer to Anya')['destination'],'pier')

    def test_negated_hearsay_and_hidden_routes_do_not_create_access(self):
        for description in ('安雅不在渡口。','聽說渡口的安雅正在工作。','Anya is not at Ferry Pier.'):
            self.state['locations']['river_street']['description']=description
            self.assertIsNone(movement(self.state,'approach Anya'))
        self.state=new_campaign();self.state['pc']['location']='river_street'
        self.state['locations']['river_street']['exits']['pier']['known']=False
        self.assertIsNone(movement(self.state,'approach Anya'))
        self.assertIsNone(movement(self.state,'go to Ferry Pier'))

    def test_extra_actions_negations_questions_and_quotes_are_not_auto_movement(self):
        for text in ('get closer to Anya and stab her','go to Anya then take her boat',
                     'do not approach Anya','I might approach Anya','"get closer to Anya"',
                     'can I get closer to Anya?','approach Anyam'):
            self.assertIsNone(movement(self.state,text))
        self.assertEqual(interpret(self.state,'"get closer to Anya"')['kind'],'speak')
        self.assertEqual(interpret(self.state,'can I get closer to Anya?')['kind'],'speak')

    def test_every_non_dialogue_reaction_uses_the_story_envelope_in_same_call(self):
        action=normalize_action({'kind':'freeform','text':'我調整雨斗篷。'})
        proposal={'outcome':'success','reason':'普通動作','narration':'你整理好雨斗篷。','events':[]}
        with patch('kobold_rpg.model._complete',return_value=proposal) as complete:
            self.assertEqual(react(self.state,action),proposal)
        self.assertEqual(complete.call_count,1)
        self.assertEqual(complete.call_args.kwargs['response_schema'],proposal_schema())


class JSONEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.proposal={'outcome':'success','reason':'普通行動','narration':'引號「{這是文字}」與換行\n仍原樣保留。','events':[]}
        self.body=json.dumps(self.proposal,ensure_ascii=False)

    def test_one_complete_json_object_can_have_backend_prose_or_fences_around_it(self):
        for raw in (self.body,'敘事前言。\n\n'+self.body,'```json\n'+self.body+'\n```',
                    '```JSON\n'+self.body+'\n```','前言\n'+self.body+'\n結尾說明。'):
            self.assertEqual(parse_proposal(raw),self.proposal)

    def test_ambiguous_duplicate_truncated_and_nonstandard_json_never_get_guessed(self):
        for raw in (self.body+self.body,'{}\n'+self.body,self.body[:-1],
                    '{"outcome":"failure","outcome":"success"}',
                    '{"value":NaN}','[{"outcome":"success"}]','{"outer":'+self.body,
                    '前言 {bad JSON}\n'+self.body,None,'普通文字沒有資料'):
            with self.subTest(raw=raw),self.assertRaises(InvalidJSONError):parse_proposal(raw)

    def test_recovered_object_still_cannot_grant_unknown_power_or_undeclared_movement(self):
        state=new_campaign();action=normalize_action({'kind':'freeform','text':'看看河流。'})
        proposal={**self.proposal,'events':[{'type':'move','destination':'pier'}]}
        recovered=parse_proposal('敘事前言\n'+json.dumps(proposal))
        with self.assertRaises(RuleError):validate_proposal(state,action,recovered)

    def test_adapter_requests_an_object_for_every_other_model_stage_without_retry(self):
        response=io.BytesIO(json.dumps({'choices':[{'message':{'content':'前言\n'+self.body}}]}).encode())
        with patch('kobold_rpg.model.urllib.request.urlopen',return_value=response) as request:
            self.assertEqual(_complete([{'role':'user','content':'test'}],'http://local',100,.2),self.proposal)
        self.assertEqual(request.call_count,1)
        payload=json.loads(request.call_args.args[0].data)
        self.assertEqual(payload['response_format']['json_schema']['schema'],{'type':'object'})


if __name__=='__main__':unittest.main()
