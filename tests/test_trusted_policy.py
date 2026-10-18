"""The Jenkins GitOps validator must use policy maintained outside its PR input."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'trusted-policy/argo-rollouts'


class TrustedPolicyTests(unittest.TestCase):
    def test_reviewed_probe_baseline_accepts_both_supported_currencies(self):
        backend = (POLICY / 'backend-check.mjs').read_text()
        checkout = (POLICY / 'checkout-check.mjs').read_text()
        self.assertIn("['USD','INR'].includes(p.currency)", backend)
        self.assertIn("assert.equal(order.currency, product.currency)", backend)
        self.assertIn("assert.equal(order.currency, product.currency)", checkout)

    def test_validator_installs_policy_from_the_trusted_ci_checkout(self):
        pipeline = (ROOT / 'pipelines/gitops-validate.Jenkinsfile').read_text()
        install = 'cp automation/trusted-policy/argo-rollouts/checkout-check.mjs tools/platform/argo-rollouts/checkout-check.mjs'
        validate = 'bash tools/scripts/validate.sh "$WORKSPACE/candidate" origin/main'
        self.assertIn(install, pipeline)
        self.assertIn('cp automation/trusted-policy/argo-rollouts/backend-check.mjs tools/platform/argo-rollouts/backend-check.mjs', pipeline)
        self.assertLess(pipeline.index(install), pipeline.index(validate))


if __name__ == '__main__':
    unittest.main()
