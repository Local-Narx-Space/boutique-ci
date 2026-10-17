import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('production_merge', Path(__file__).parents[1] / 'scripts/production-merge.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
HEAD = 'a' * 40
MERGE = 'b' * 40


class ProductionMergeTests(unittest.TestCase):
    def setUp(self):
        self.pr = {
            'state': 'open', 'merged': False,
            'head': {'sha': HEAD, 'ref': 'jenkins/promote/production/frontend/12', 'repo': {'full_name': module.REPO}},
            'base': {'ref': 'main', 'repo': {'full_name': module.REPO}},
        }

    def test_open_waits_and_closed_unmerged_stops(self):
        self.assertEqual(module.inspect(self.pr, HEAD), {'state': 'waiting'})
        self.pr['state'] = 'closed'
        self.assertEqual(module.inspect(self.pr, HEAD), {'state': 'closed'})

    def test_exact_merge_selects_each_service(self):
        for service in ['frontend', 'catalogue', 'cart', 'orders']:
            self.pr.update(state='closed', merged=True, merge_commit_sha=MERGE)
            self.pr['head']['ref'] = f'jenkins/promote/production/{service}/12'
            self.assertEqual(module.inspect(self.pr, HEAD), {'state': 'merged', 'commit': MERGE, 'service': service})

    def test_rejects_changed_head_fork_wrong_base_and_other_branches(self):
        for section, key, value in [
            ('head', 'sha', 'c' * 40),
            ('head', 'repo', {'full_name': 'attacker/boutique-gitops'}),
            ('base', 'repo', {'full_name': 'attacker/boutique-gitops'}),
            ('base', 'ref', 'other'),
            ('head', 'ref', 'jenkins/promote/dev/frontend/12'),
            ('head', 'ref', 'jenkins/rollback/production/frontend/12'),
            ('head', 'ref', 'jenkins/promote/production/frontend/12/suffix'),
        ]:
            with self.subTest(section=section, key=key, value=value):
                pr = copy.deepcopy(self.pr)
                pr[section][key] = value
                with self.assertRaises(ValueError):
                    module.inspect(pr, HEAD)

    def test_rejects_missing_or_invalid_merge_commit(self):
        self.pr.update(state='closed', merged=True)
        for sha in ['', 'main', 'b' * 39, 'b' * 41]:
            self.pr['merge_commit_sha'] = sha
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                module.inspect(self.pr, HEAD)

    def test_rejects_unknown_state_and_invalid_expected_head(self):
        with self.assertRaises(ValueError):
            module.inspect(self.pr, 'main')
        self.pr['state'] = 'unknown'
        with self.assertRaises(ValueError):
            module.inspect(self.pr, HEAD)


if __name__ == '__main__':
    unittest.main()
