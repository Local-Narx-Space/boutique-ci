import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
import urllib.error

spec = importlib.util.spec_from_file_location('release_merge', Path(__file__).parents[1] / 'scripts/release-merge.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
HEAD = 'a' * 40
MERGE = 'b' * 40


class ReleaseMergeTests(unittest.TestCase):
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
        for target in ['dev', 'staging', 'production']:
            for service in ['frontend', 'catalogue', 'cart', 'orders']:
                with self.subTest(target=target, service=service):
                    self.pr.update(state='closed', merged=True, merge_commit_sha=MERGE)
                    self.pr['head']['ref'] = f'jenkins/promote/{target}/{service}/12'
                    self.assertEqual(module.inspect(self.pr, HEAD), {'state': 'merged', 'commit': MERGE, 'service': service, 'target': target})

    def test_rejects_changed_head_fork_wrong_base_and_other_branches(self):
        for section, key, value in [
            ('head', 'sha', 'c' * 40),
            ('head', 'repo', {'full_name': 'attacker/boutique-gitops'}),
            ('base', 'repo', {'full_name': 'attacker/boutique-gitops'}),
            ('base', 'ref', 'other'),
            ('head', 'ref', 'jenkins/promote/preview/frontend/12'),
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


class AutomaticPromotionTests(unittest.TestCase):
    def setUp(self):
        self.pr = {'state': 'open', 'draft': False, 'changed_files': 3,
                   'user': {'login': 'release-app[bot]', 'type': 'Bot', 'id': 123},
                   'head': {'sha': HEAD, 'ref': 'jenkins/promote/dev/frontend/12', 'repo': {'full_name': module.REPO}},
                   'base': {'ref': 'main', 'repo': {'full_name': module.REPO}}}
        self.files = [{'filename': f'environments/dev/{path}'} for path in
                      ['Chart.yaml', 'releases.yaml', 'charts/boutique-frontend-0.1.0-' + HEAD + '.tgz']]
        self.values = {s: {'image': {'repository': 'ghcr.io/subhankar12-spec/boutique-' + s,
                                    'digest': 'sha256:' + 'a' * 64, 'tag': ''}}
                       for s in ['frontend', 'catalogue', 'cart', 'orders']}
        self.chart = {'name': 'boutique-dev', 'dependencies': [
            {'name': 'boutique-' + s, 'alias': s, 'version': '0.1.0-bootstrap',
             'repository': 'oci://ghcr.io/subhankar12-spec/charts'} for s in self.values]}

    def eligible(self):
        return module.automatic_request(self.pr, HEAD, self.files, 'release-app[bot]', '123')

    def test_only_app_owned_dev_and_staging_promotions_qualify(self):
        for target in ['dev', 'staging']:
            self.pr['head']['ref'] = f'jenkins/promote/{target}/frontend/12'
            files = [{'filename': f['filename'].replace('/dev/', '/' + target + '/')} for f in self.files]
            result = module.automatic_request(self.pr, HEAD, files, 'release-app[bot]', '123')
            self.assertEqual(result['target'], target)

    def test_production_rollback_and_configuration_never_auto_merge(self):
        for branch in ['jenkins/promote/production/frontend/12', 'jenkins/rollback/dev/frontend/12', 'feature/configuration']:
            self.pr['head']['ref'] = branch
            self.assertIsNone(self.eligible())

    def test_wrong_author_bot_id_type_draft_and_head_are_rejected(self):
        for field, value in [('login', 'developer'), ('id', 999), ('type', 'User')]:
            pr = copy.deepcopy(self.pr)
            pr['user'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.automatic_request(pr, HEAD, self.files, 'release-app[bot]', '123')
        self.pr['draft'] = True
        with self.assertRaises(ValueError): self.eligible()
        self.pr['draft'] = False
        self.pr['head']['sha'] = MERGE
        with self.assertRaises(ValueError): self.eligible()

    def test_unexpected_paths_other_charts_and_renamed_code_are_rejected(self):
        for path in ['.github/CODEOWNERS', 'scripts/promote.py', 'environments/dev/values.yaml',
                     'environments/production/releases.yaml', 'environments/dev/charts/boutique-orders-a.tgz']:
            files = copy.deepcopy(self.files)
            files[0]['filename'] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                module.automatic_request(self.pr, HEAD, files, 'release-app[bot]', '123')
        self.files[2]['previous_filename'] = 'scripts/promote.py'
        with self.assertRaises(ValueError): self.eligible()

    def test_incomplete_file_lists_are_rejected(self):
        self.pr['changed_files'] = 4
        with self.assertRaises(ValueError): self.eligible()

    def test_only_selected_image_and_dependency_version_can_change(self):
        values, chart = copy.deepcopy(self.values), copy.deepcopy(self.chart)
        values['frontend']['image']['digest'] = 'sha256:' + 'b' * 64
        chart['dependencies'][0]['version'] = '0.1.0-' + HEAD
        module.validate_documents(self.values, values, self.chart, chart, 'frontend')
        for changed in ['other_image', 'config', 'metadata', 'dependency']:
            v, c = copy.deepcopy(values), copy.deepcopy(chart)
            if changed == 'other_image': v['orders']['image']['digest'] = 'sha256:' + 'c' * 64
            if changed == 'config': v['frontend']['replicas'] = 99
            if changed == 'metadata': c['name'] = 'unreviewed'
            if changed == 'dependency': c['dependencies'][1]['version'] = '0.1.0-' + MERGE
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                module.validate_documents(self.values, v, self.chart, c, 'frontend')

    def test_merge_uses_exact_head_and_normal_merge_api(self):
        calls = []
        def opener(request, timeout):
            calls.append(request)
            return io.StringIO(json.dumps({'merged': True, 'sha': MERGE}))
        self.assertTrue(module.merge('12', HEAD, 'fixture-token', opener)['merged'])
        self.assertEqual(calls[0].full_url, f'https://api.github.com/repos/{module.REPO}/pulls/12/merge')
        self.assertEqual(json.loads(calls[0].data), {'sha': HEAD, 'merge_method': 'squash'})

    def test_github_refusal_does_not_count_as_success(self):
        for code in [403, 405, 409]:
            def opener(request, timeout):
                raise urllib.error.HTTPError(request.full_url, code, 'refused', {}, None)
            with self.subTest(code=code), self.assertRaises(ValueError):
                module.merge('12', HEAD, 'fixture-token', opener, sleep=lambda _: None)

    def retry_opener(self, outcomes, snapshot=None):
        calls = []
        pr = copy.deepcopy(self.pr if snapshot is None else snapshot)
        if snapshot is None:
            pr.update(mergeable=True, mergeable_state='clean')
        def opener(request, timeout):
            calls.append(request)
            if request.get_method() == 'GET':
                return io.StringIO(json.dumps(pr))
            outcome = outcomes.pop(0)
            if isinstance(outcome, int):
                raise urllib.error.HTTPError(request.full_url, outcome, 'refused', {}, None)
            return io.StringIO(json.dumps(outcome))
        return opener, calls

    def test_transient_405_rechecks_head_and_retries_same_sha(self):
        opener, calls = self.retry_opener([405, 405, {'merged': True, 'sha': MERGE}])
        sleeps = []
        self.assertTrue(module.merge('12', HEAD, 'fixture-token', opener, sleeps.append)['merged'])
        self.assertEqual(sleeps, [5, 10])
        self.assertEqual([c.get_method() for c in calls], ['PUT', 'GET', 'PUT', 'GET', 'PUT'])
        for c in calls:
            if c.get_method() == 'PUT': self.assertEqual(json.loads(c.data)['sha'], HEAD)

    def test_retry_budget_is_bounded(self):
        opener, calls = self.retry_opener([405] * 5)
        sleeps = []
        with self.assertRaisesRegex(ValueError, 'after 5 attempts'):
            module.merge('12', HEAD, 'fixture-token', opener, sleeps.append)
        self.assertEqual(sleeps, [5, 10, 20, 40])
        self.assertEqual(sum(c.get_method() == 'PUT' for c in calls), 5)

    def test_unknown_mergeability_can_settle(self):
        pr = copy.deepcopy(self.pr)
        pr.update(mergeable=None, mergeable_state='unknown')
        opener, _ = self.retry_opener([405, {'merged': True, 'sha': MERGE}], pr)
        self.assertTrue(module.merge('12', HEAD, 'fixture-token', opener, lambda _: None)['merged'])

    def test_changed_head_conflict_closed_draft_or_policy_block_stops_retry(self):
        for change in ['head', 'conflict', 'closed', 'draft', 'blocked', 'behind']:
            pr = copy.deepcopy(self.pr)
            pr.update(mergeable=True, mergeable_state='clean')
            if change == 'head': pr['head']['sha'] = MERGE
            elif change == 'conflict': pr['mergeable'] = False
            elif change == 'closed': pr['state'] = 'closed'
            elif change == 'draft': pr['draft'] = True
            else: pr['mergeable_state'] = change
            opener, calls = self.retry_opener([405], pr)
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.merge('12', HEAD, 'fixture-token', opener, lambda _: None)
            self.assertEqual([c.get_method() for c in calls], ['PUT', 'GET'])

    def test_permission_and_head_refusals_are_not_retried(self):
        for code in [403, 409, 422]:
            opener, calls = self.retry_opener([code])
            sleeps = []
            with self.subTest(code=code), self.assertRaises(ValueError):
                module.merge('12', HEAD, 'fixture-token', opener, sleeps.append)
            self.assertEqual(sleeps, [])
            self.assertEqual(len(calls), 1)

    def test_another_worker_merging_exact_head_is_success(self):
        pr = copy.deepcopy(self.pr)
        pr.update(state='closed', merged=True, merge_commit_sha=MERGE)
        opener, calls = self.retry_opener([405], pr)
        self.assertEqual(module.merge('12', HEAD, 'fixture-token', opener, lambda _: None),
                         {'merged': True, 'commit': MERGE})
        self.assertEqual([c.get_method() for c in calls], ['PUT', 'GET'])

    def test_authenticated_redirect_is_refused(self):
        with self.assertRaises(ValueError):
            module.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example')


class ReviewPolicyTests(unittest.TestCase):
    def test_checks_are_never_bypassed_and_only_app_can_skip_review_in_prs(self):
        policy = json.loads((Path(__file__).parents[1] / 'jenkins/policies/gitops-rulesets.json').read_text())
        checks, review, branches = [r['definition'] for r in policy['rulesets']]
        self.assertEqual(checks['bypass_actors'], [])
        self.assertEqual({r['type'] for r in checks['rules']}, {'required_status_checks', 'deletion', 'non_fast_forward', 'required_linear_history'})
        self.assertEqual(review['bypass_actors'], [{'actor_id': 5369366, 'actor_type': 'Integration', 'bypass_mode': 'pull_request'}])
        requirement = review['rules'][0]['parameters']
        self.assertEqual(requirement['required_approving_review_count'], 1)
        self.assertTrue(requirement['require_code_owner_review'])
        self.assertEqual(branches['conditions']['ref_name']['include'], ['refs/heads/jenkins/promote/*/*/*'])
        self.assertEqual({r['type'] for r in branches['rules']}, {'creation', 'update'})


if __name__ == '__main__':
    unittest.main()
