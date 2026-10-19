"""Post bounded release notifications without exposing the channel webhook."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

EVENTS = {
    'build_failed': ('Build failed', '#d50200'),
    'deployment_started': ('Deployment verification started', '#439fe0'),
    'deployment_passed': ('Deployment verified: rollout and smoke checks passed', '#2eb886'),
    'deployment_failed': ('Deployment verification failed: promotion blocked', '#d50200'),
    'rollback_recovered': ('Rollout aborted: stable traffic recovered; promotion blocked', '#d50200'),
    'approval_required': ('Production release ready for review', '#daa038'),
    'recovery_review': ('Recovery PR ready for human review', '#daa038'),
    'pipeline_failed': ('Release automation failed: inspect Jenkins', '#d50200'),
    'test': ('Slack delivery connection verified', '#2eb886'),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('Webhook redirect refused')


def payload(env):
    title, color = EVENTS[env['NOTICE_EVENT']]
    service = env.get('NOTICE_SERVICE', '')
    target = env.get('NOTICE_TARGET', '')
    if service and service not in ('frontend', 'catalogue', 'cart', 'orders'):
        raise ValueError('Invalid service')
    if target and target not in ('dev', 'staging', 'production'):
        raise ValueError('Invalid environment')
    label = {'staging': 'QA', 'production': 'Production', 'dev': 'Dev'}.get(target, '')
    text = ' | '.join(x for x in ('Boutique', label, service, title) if x)
    blocks = [{'type': 'section', 'text': {'type': 'plain_text', 'text': text}}]
    links = []
    for key, pattern, name in [
        ('BUILD_URL', r'https://jenkins\.narx\.space/(?:job/[A-Za-z0-9_.% -]+/)+[0-9]+/', 'Jenkins build'),
        ('NOTICE_PR_URL', r'https://github\.com/Local-Narx-Space/boutique-gitops/pull/[1-9][0-9]*', 'GitOps PR'),
    ]:
        url = env.get(key, '')
        if url:
            if not re.fullmatch(pattern, url):
                raise ValueError('Unexpected notification link')
            links.append(f'<{url.replace(" ", "%20")}|{name}>')
    if links:
        blocks.append({'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': ' · '.join(links)}]})
    return {'text': text, 'attachments': [{'color': color, 'blocks': blocks}],
            'unfurl_links': False, 'unfurl_media': False}


def send(webhook, message, opener=None, sleep=time.sleep):
    if not re.fullmatch(r'https://hooks\.slack\.com/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]+', webhook):
        raise ValueError('Expected a Slack channel webhook')
    opener = opener or urllib.request.build_opener(NoRedirect()).open
    request = urllib.request.Request(webhook, data=json.dumps(message).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
    for attempt in range(2):
        try:
            with opener(request, timeout=10) as response:
                if response.status != 200 or response.read(64).strip() != b'ok':
                    raise ValueError('Slack did not acknowledge delivery')
            return
        except urllib.error.HTTPError as error:
            # No retry for permissions, revoked URLs, redirects or invalid payloads.
            if attempt == 0 and error.code == 429:
                delay = error.headers.get('Retry-After', '')
                if delay.isdigit() and 0 <= int(delay) <= 10:
                    sleep(int(delay))
                    continue
            raise ValueError('Slack refused delivery') from None


def main():
    try:
        send(os.environ['SLACK_WEBHOOK_URL'], payload(os.environ))
    except Exception:
        # Never print exception bodies/URLs: the webhook itself is a credential.
        print('Slack notification was not delivered; deployment result is unchanged.', file=sys.stderr)
        return 1
    print('Slack notification delivered.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
