"""Jenkins coordinates releases after the GitOps Actions checks complete."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GitOpsOrchestrationTests(unittest.TestCase):
    def test_waits_for_required_checks_and_does_not_repeat_manifest_validation(self):
        pipeline = (ROOT / 'pipelines/gitops-validate.Jenkinsfile').read_text()
        self.assertIn("stage('Wait for required GitHub PR checks')", pipeline)
        self.assertIn('gh pr checks "$PR_NUMBER" --repo Local-Narx-Space/boutique-gitops --required --watch --fail-fast', pipeline)
        self.assertIn('test "$CURRENT_HEAD" = "$PR_HEAD_SHA"', pipeline)
        self.assertNotIn('scripts/validate.sh', pipeline)
        self.assertNotIn("context='boutique/gitops-validation'", pipeline)


if __name__ == '__main__':
    unittest.main()
