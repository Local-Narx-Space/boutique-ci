#!/usr/bin/env python3
"""Wait for required GitOps checks, including their initial registration window."""
import argparse
import json
import re
import subprocess
import time

REPO = 'Local-Narx-Space/boutique-gitops'
REQUIRED = {'PR checks', 'GitOps manifest validation'}


def check_state(runs):
    selected = {name: [r for r in runs if r['name'] == name and r.get('app', {}).get('id') == 15368] for name in REQUIRED}
    # GitHub returns newest runs first. A new attempt supersedes older attempts.
    latest = {name: runs[0] for name, runs in selected.items() if runs}
    for name, run in latest.items():
        if run['status'] == 'completed' and run['conclusion'] != 'success':
            raise ValueError(f'Required check failed: {name}')
    return REQUIRED == latest.keys() and all(r['status'] == 'completed' for r in latest.values())


def api(path):
    result = subprocess.run(['gh', 'api', path], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('GitHub check lookup failed; verify App access and API availability')
    return json.loads(result.stdout)


def wait(pr, head, timeout, interval=10, fetch=api, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while True:
        current = fetch(f'repos/{REPO}/pulls/{pr}')
        if (current['head']['sha'] != head or current['base']['ref'] != 'main'
                or current['head']['repo']['full_name'] != REPO):
            raise ValueError('PR identity or head changed; validate the new revision instead')
        if current['state'] == 'closed' and not current.get('merged'):
            raise ValueError('PR closed without merge')
        checks = fetch(f'repos/{REPO}/commits/{head}/check-runs?per_page=100&filter=latest')['check_runs']
        if check_state(checks):
            return
        if clock() >= deadline:
            raise ValueError('Timed out waiting for required GitOps checks')
        sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pr', required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    if not re.fullmatch(r'[1-9][0-9]*', args.pr) or not re.fullmatch(r'[a-f0-9]{40}', args.head):
        parser.error('Numeric PR and full head SHA required')
    try:
        wait(args.pr, args.head, args.timeout)
    except (ValueError, KeyError, TypeError) as error:
        raise SystemExit(str(error))
    print('Both required GitOps checks passed for the requested head.')


if __name__ == '__main__':
    main()
