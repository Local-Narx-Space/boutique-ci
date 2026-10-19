#!/usr/bin/env python3
"""Inspect a release PR without approving or merging it."""
import argparse
import json
import re
from pathlib import Path

REPO = 'Local-Narx-Space/boutique-gitops'
SHA = re.compile(r'[a-f0-9]{40}')
BRANCH = re.compile(r'jenkins/promote/(dev|staging|production)/(frontend|catalogue|cart|orders)/[1-9][0-9]*')


def inspect(pr, head):
    match = BRANCH.fullmatch(pr.get('head', {}).get('ref', ''))
    if (not match or not SHA.fullmatch(head)
            or pr.get('head', {}).get('sha') != head
            or pr.get('head', {}).get('repo', {}).get('full_name') != REPO
            or pr.get('base', {}).get('repo', {}).get('full_name') != REPO
            or pr.get('base', {}).get('ref') != 'main'):
        raise ValueError('Expected the unchanged validated release PR against GitOps main')
    if pr.get('merged') is True:
        commit = pr.get('merge_commit_sha', '')
        if pr.get('state') != 'closed' or not SHA.fullmatch(commit):
            raise ValueError('Merged PR requires a full merge commit')
        return {'state': 'merged', 'commit': commit, 'service': match[2], 'target': match[1]}
    if pr.get('state') == 'closed':
        return {'state': 'closed'}
    if pr.get('state') != 'open':
        raise ValueError('Unexpected PR state')
    return {'state': 'waiting'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pr', required=True)
    parser.add_argument('--head', required=True)
    args = parser.parse_args()
    try:
        result = inspect(json.loads(Path(args.pr).read_text()), args.head)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise SystemExit(str(error))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
