"""Jenkins coordinates releases after the GitOps Actions checks complete."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GitOpsOrchestrationTests(unittest.TestCase):
    def test_waits_for_required_checks_and_does_not_repeat_manifest_validation(self):
        pipeline = (ROOT / 'pipelines/gitops-validate.Jenkinsfile').read_text()
        self.assertIn("stage('Wait for required GitHub PR checks')", pipeline)
        self.assertIn('python3 automation/scripts/wait-for-pr-checks.py --pr "$PR_NUMBER" --head "$PR_HEAD_SHA"', pipeline)
        self.assertIn('test "$CURRENT_HEAD" = "$PR_HEAD_SHA"', pipeline)
        self.assertNotIn('scripts/validate.sh', pipeline)
        self.assertIn('Release Operations/boutique-release-verify', pipeline)
        self.assertIn('(dev|staging|production)', pipeline)
        self.assertNotIn('merge_method=squash', pipeline)
        self.assertNotIn('automatic-release.py', pipeline)
        self.assertNotIn("context='boutique/gitops-validation'", pipeline)


if __name__ == '__main__':
    unittest.main()
