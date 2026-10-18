"""Disposable negative test: this PR must be blocked and closed, never merged."""
import unittest
class RequiredCheckProbe(unittest.TestCase):
    def test_expected_failure(self):
        self.fail("Intentional branch-protection acceptance probe; do not merge")
