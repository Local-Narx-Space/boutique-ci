"""The Jenkins GitOps validator must use policy maintained outside its PR input."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'trusted-policy/argo-rollouts'


class TrustedPolicyTests(unittest.TestCase):
    def test_controller_assets_match_the_reviewed_release_lock(self):
        lock = json.loads((POLICY / 'release-lock.json').read_text())
        for name, expected in lock['assets'].items():
            with self.subTest(asset=name):
                self.assertEqual(hashlib.sha256((POLICY / name).read_bytes()).hexdigest(), expected)

    def test_validator_installs_policy_from_the_trusted_ci_checkout(self):
        pipeline = (ROOT / 'pipelines/gitops-validate.Jenkinsfile').read_text()
        install = 'cp -a automation/trusted-policy/argo-rollouts/. tools/platform/argo-rollouts/'
        validate = 'bash tools/scripts/validate.sh "$WORKSPACE/candidate" origin/main'
        self.assertIn(install, pipeline)
        self.assertLess(pipeline.index(install), pipeline.index(validate))


if __name__ == '__main__':
    unittest.main()
