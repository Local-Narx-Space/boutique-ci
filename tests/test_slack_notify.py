import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock
import contextlib
import urllib.error

spec = importlib.util.spec_from_file_location('slack_notify', Path(__file__).parents[1] / 'resources/boutique/slack_notify.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
WEBHOOK = 'https://hooks.slack.com/services/TEAM/CHANNEL/fixture'


class Response(io.BytesIO):
    status = 200


class SlackTests(unittest.TestCase):
    def test_payload_links_and_rollback_are_explicit(self):
        env = {'NOTICE_EVENT': 'rollback_recovered', 'NOTICE_SERVICE': 'frontend', 'NOTICE_TARGET': 'staging',
               'BUILD_URL': 'https://jenkins.narx.space/job/Deployments/job/boutique-deploy-qa/46/'}
        p = m.payload(env)
        self.assertIn('stable traffic recovered', p['text'])
        self.assertIn('QA', p['text'])
        self.assertNotIn(WEBHOOK, json.dumps(p))
        self.assertNotIn('channel', p)

    def test_untrusted_links_services_and_events_are_rejected(self):
        for field, value in [('BUILD_URL', 'https://evil.example/'), ('NOTICE_PR_URL', '<!channel>'),
                             ('NOTICE_SERVICE', '<!here>'), ('NOTICE_EVENT', 'made-up')]:
            with self.subTest(field=field), self.assertRaises((ValueError, KeyError)):
                m.payload({'NOTICE_EVENT': 'test', field: value})

    def test_posts_json_with_timeout_and_requires_slack_ack(self):
        calls = []
        def opener(req, timeout):
            calls.append((req, timeout))
            return Response(b'ok')
        m.send(WEBHOOK, {'text': 'fixture'}, opener)
        req, timeout = calls[0]
        self.assertEqual(req.get_method(), 'POST')
        self.assertEqual(json.loads(req.data), {'text': 'fixture'})
        self.assertEqual(timeout, 10)
        with self.assertRaises(ValueError):
            m.send(WEBHOOK, {}, lambda *a, **k: Response(b'not_ok'))

    def test_only_slack_https_webhook_is_accepted(self):
        for url in ['http://hooks.slack.com/services/A/B/C', 'https://evil.example/services/A/B/C',
                    WEBHOOK + '?secret=1', WEBHOOK + '#fragment', 'https://user@hooks.slack.com/services/A/B/C']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                m.send(url, {}, lambda *a, **k: self.fail('must not connect'))

    def test_rate_limit_retries_once_with_bounded_retry_after(self):
        calls, waits = [], []
        def opener(req, timeout):
            calls.append(req)
            if len(calls) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, 'limited', {'Retry-After': '2'}, None)
            return Response(b'ok')
        m.send(WEBHOOK, {}, opener, waits.append)
        self.assertEqual(waits, [2])
        self.assertEqual(len(calls), 2)

    def test_permanent_errors_and_long_rate_limits_do_not_retry(self):
        for code, delay in [(403, '1'), (404, '1'), (500, '1'), (429, '120')]:
            calls, waits = [], []
            def opener(req, timeout):
                calls.append(req)
                raise urllib.error.HTTPError(req.full_url, code, 'fixture', {'Retry-After': delay}, None)
            with self.subTest(code=code), self.assertRaises(ValueError):
                m.send(WEBHOOK, {}, opener, waits.append)
            self.assertEqual(len(calls), 1)
            self.assertEqual(waits, [])

    def test_redirect_cannot_expose_webhook(self):
        with self.assertRaises(ValueError):
            m.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example')

    def test_failure_output_never_contains_webhook_or_exception_details(self):
        output = io.StringIO()
        with mock.patch.dict(m.os.environ, {'SLACK_WEBHOOK_URL': WEBHOOK, 'NOTICE_EVENT': 'test'}), \
             mock.patch.object(m, 'send', side_effect=OSError(WEBHOOK)), contextlib.redirect_stderr(output):
            self.assertEqual(m.main(), 1)
        self.assertNotIn(WEBHOOK, output.getvalue())
        self.assertIn('deployment result is unchanged', output.getvalue())
