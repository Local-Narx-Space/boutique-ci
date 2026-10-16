#!/usr/bin/env python3
"""Authorize only unchanged, bot-owned service promotion PRs for automatic merge."""
import argparse
import json
from pathlib import Path
import re
import subprocess

REPO = 'subhankar12-spec/boutique-gitops'
BRANCH = re.compile(r'jenkins/promote/(dev|staging)/(frontend|catalogue|cart|orders)/[1-9][0-9]*')


def request(pr, bot, head, paths):
    match = BRANCH.fullmatch(pr.get('head', {}).get('ref', ''))
    if not match:
        return None  # Production, rollback and human configuration PRs require review.
    if (pr.get('state') != 'open' or pr.get('draft')
            or pr.get('base', {}).get('ref') != 'main'
            or pr.get('head', {}).get('repo', {}).get('full_name') != REPO
            or pr.get('user', {}).get('login') != bot
            or pr.get('head', {}).get('sha') != head
            or not re.fullmatch(r'[a-f0-9]{40}', head)):
        raise ValueError('Automatic promotion requires the validated bot-owned PR head')
    target, service = match.groups()
    allowed = re.compile(rf'environments/{target}/(?:Chart\.yaml|releases\.yaml|charts/boutique-{service}-[^/]+\.tgz)')
    if not paths or any(not allowed.fullmatch(path) for path in paths):
        raise ValueError('Automatic promotion cannot change configuration, code or another service chart')
    return {'target': target, 'service': service, 'head': head}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pr', required=True)
    p.add_argument('--bot', required=True)
    p.add_argument('--head', required=True)
    p.add_argument('--candidate', required=True)
    args = p.parse_args()
    paths = subprocess.check_output(['git', '-C', args.candidate, 'diff', '--name-only',
                                     'origin/main...HEAD'], text=True).splitlines()
    try:
        result = request(json.loads(Path(args.pr).read_text()), args.bot, args.head, paths)
    except (ValueError, TypeError, KeyError) as error:
        raise SystemExit(str(error))
    print(json.dumps(result))

if __name__ == '__main__':
    main()
