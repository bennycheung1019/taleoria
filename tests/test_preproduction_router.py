import copy
import tempfile
import unittest
from pathlib import Path

from kobold_rpg.engine import RuleError
from kobold_rpg.engine import Engine
from kobold_rpg.condition_state_trial import make_condition_gm
from kobold_rpg.preproduction import make_preproduction_gm
from test_library import fixture as world_fixture
from test_structured_state_trial import action


class PreproductionRouterTests(unittest.TestCase):
    def test_unsupported_action_uses_legacy_and_current_campaign(self):
        class Library:
            engine = object()
        library = Library()
        seen = []
        def trial_factory(engine):
            seen.append(engine)
            def trial(*args, **kwargs):
                raise RuleError('此動作尚未有安全的裁定及敘述流程。')
            return trial
        def fallback(*args, **kwargs):
            return {'narration': 'fallback', 'changes': {}}
        gm = make_preproduction_gm(library, trial_factory=trial_factory,
                                    fallback=fallback)
        self.assertEqual(gm({}, 'talk', 'http://127.0.0.1:5001')['narration'],
                         'fallback')
        library.engine = object()
        gm({}, 'talk', 'http://127.0.0.1:5001')
        self.assertIs(seen[-1], library.engine)
        self.assertIsNot(seen[0], seen[-1])

    def test_validation_failure_never_falls_back(self):
        class Library:
            engine = object()
        def trial_factory(engine):
            def trial(*args, **kwargs):
                raise RuleError('初始完整度缺少明確的完整外觀來源。')
            return trial
        def fallback(*args, **kwargs):
            self.fail('unsafe fallback')
        gm = make_preproduction_gm(Library(), trial_factory=trial_factory,
                                    fallback=fallback)
        with self.assertRaisesRegex(RuleError, '初始完整度'):
            gm({}, 'break door', 'http://127.0.0.1:5001')

    def test_unadjudicated_force_uses_legacy(self):
        class Library:
            engine = object()
        def trial_factory(engine):
            def trial(*args, **kwargs):
                raise RuleError('完整度只適用於已裁定的單一動作。')
            return trial
        def fallback(*args, **kwargs):
            return {'narration': 'legacy', 'changes': {}}
        gm = make_preproduction_gm(Library(), trial_factory=trial_factory,
                                    fallback=fallback)
        self.assertEqual(gm({}, 'break door', 'http://127.0.0.1:5001')['narration'],
                         'legacy')

    def test_english_ask_him_uses_only_present_npc_dialogue(self):
        seed=world_fixture()['seed'];calls=[]
        def complete(messages,*args,**kwargs):
            calls.append(messages)
            return {'narration':'小禾說：「我只知道你喺店門外，之前發生咩事我唔清楚。」'}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            before=engine.state()
            reply=make_condition_gm(engine,complete=complete)(
                before,'ask him why am i here','http://none')
            self.assertEqual(len(calls),1)
            self.assertIn('ask 小禾',calls[0][0]['content'])
            self.assertEqual(reply['changes'],{'scene_focus':['guide']})
            self.assertEqual(engine.state(),before)
            named=make_condition_gm(engine,complete=complete)(
                before,'ask Xiao He why am i here','http://none')
            self.assertEqual(named['changes'],{'scene_focus':['guide']})
            self.assertEqual(len(calls),2)

    def test_pronoun_with_two_present_people_requests_clarification(self):
        seed=world_fixture()['seed']
        seed['npcs']['second']=copy.deepcopy(seed['npcs']['guide'])
        seed['npcs']['second']['name']='阿琳（Ah Lam）'
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            with self.assertRaisesRegex(RuleError,'多名人物'):
                make_condition_gm(engine,complete=lambda *a,**k:self.fail('no call'))(
                    seed,'ask him why am i here','http://none')
            self.assertEqual(engine.state()['revision'],0)

    def test_request_to_unstructured_npc_falls_back_without_decision(self):
        seed=world_fixture()['seed'];calls=[]
        def complete(messages,*args,**kwargs):
            calls.append(messages)
            return {'mode':'play','steps':[action('persuade','guide')]}
        def fallback(*args,**kwargs):
            return {'narration':'小禾聽了你的請求，還沒有答應。','changes':{}}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=seed)
            class Library:
                pass
            library=Library();library.engine=engine
            gm=make_preproduction_gm(
                library,trial_factory=lambda current:make_condition_gm(current,complete=complete),
                fallback=fallback)
            reply=gm(seed,'ask him to open the door','http://none')
            self.assertEqual(reply['changes'],{})
            self.assertEqual(len(calls),1)
            self.assertEqual(engine.state()['revision'],0)


if __name__ == '__main__':
    unittest.main()
