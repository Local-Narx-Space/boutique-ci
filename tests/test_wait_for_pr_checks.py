import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('wait_checks', Path(__file__).parents[1] / 'scripts/wait-for-pr-checks.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
HEAD = 'a' * 40


class WaitChecksTests(unittest.TestCase):
    def setUp(self):
        self.pr = {'state': 'open', 'head': {'sha': HEAD, 'repo': {'full_name': module.REPO}}, 'base': {'ref': 'main'}}
        self.runs = [{'name': name, 'status': 'completed', 'conclusion': 'success', 'app': {'id': 15368}} for name in module.REQUIRED]

    def test_both_required_checks_must_register_and_finish(self):
        self.assertFalse(module.check_state([]))
        self.assertFalse(module.check_state(self.runs[:1]))
        self.assertTrue(module.check_state(self.runs))
        self.runs[0].update(status='in_progress', conclusion=None)
        self.assertFalse(module.check_state(self.runs))

    def test_checks_from_another_app_cannot_satisfy_required_checks(self):
        runs = copy.deepcopy(self.runs)
        runs[0]['app']['id'] = 999
        self.assertFalse(module.check_state(runs))

    def test_failed_or_cancelled_checks_fail_closed(self):
        for conclusion in ['failure', 'cancelled', 'timed_out', 'skipped']:
            runs = copy.deepcopy(self.runs)
            runs[0]['conclusion'] = conclusion
            with self.subTest(conclusion=conclusion), self.assertRaises(ValueError):
                module.check_state(runs)

    def test_rerun_supersedes_old_failure(self):
        failed = dict(self.runs[0], conclusion='failure')
        self.assertTrue(module.check_state(self.runs + [failed]))

    def test_initial_registration_gap_is_retried(self):
        attempts = iter([[], self.runs])
        sleeps = []
        def fetch(path):
            return self.pr if '/pulls/' in path else {'check_runs': next(attempts)}
        module.wait('12', HEAD, 30, fetch=fetch, clock=lambda: 0, sleep=sleeps.append)
        self.assertEqual(sleeps, [10])

    def test_changed_head_and_closed_pr_stop(self):
        for change in ['head', 'closed']:
            pr = copy.deepcopy(self.pr)
            if change == 'head':
                pr['head']['sha'] = 'b' * 40
            else:
                pr['state'] = 'closed'
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.wait('12', HEAD, 30, fetch=lambda path: pr)

    def test_missing_checks_timeout(self):
        times = iter([0, 31])
        def fetch(path):
            return self.pr if '/pulls/' in path else {'check_runs': []}
        with self.assertRaisesRegex(ValueError, 'Timed out'):
            module.wait('12', HEAD, 30, fetch=fetch, clock=lambda: next(times))


if __name__ == '__main__':
    unittest.main()
