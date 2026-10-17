"""Authenticated Jenkins validation requests must not follow redirects."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('validator', Path(__file__).parents[1] / 'jenkins/scripts/validate-pipelines.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class PipelineValidationTests(unittest.TestCase):
    def test_authenticated_redirect_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'redirected'):
            validator.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid')


if __name__ == '__main__':
    unittest.main()
