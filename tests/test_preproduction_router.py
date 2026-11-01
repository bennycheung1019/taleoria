import unittest

from kobold_rpg.engine import RuleError
from kobold_rpg.preproduction import make_preproduction_gm


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


if __name__ == '__main__':
    unittest.main()
