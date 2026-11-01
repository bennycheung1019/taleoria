#!/usr/bin/env python3
"""Run the regression suite; --no-network explicitly omits socket integration tests."""
import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SOCKET_CLASSES = {'test_async_jobs.AsyncGenerationTests','test_companion.CompanionTests',
                  'test_gm_mode.GMDefaultAPITests',
                  'test_calibrated_e2e_trial.CalibratedHTTPTrialTests'}
SOCKET_METHODS = {
    'test_progress_names.ProgressTests.test_stream_completion_consumes_fragments_without_publishing_prose',
    'test_condition_state_trial.ConditionStateTrialTests.test_injected_http_turn_commits_numeric_condition_once',
}


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-network', action='store_true')
    args = parser.parse_args()
    tests = list(flatten(unittest.defaultTestLoader.discover(str(ROOT / 'tests'))))
    omitted = []
    if args.no_network:
        omitted = [t for t in tests if t.id().rsplit('.', 1)[0] in SOCKET_CLASSES or t.id() in SOCKET_METHODS]
        tests = [t for t in tests if t not in omitted]
        print(f'明確略過 {len(omitted)} 個需本機 socket 的整合測試；這些測試尚未驗證。', flush=True)
    result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(tests))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
