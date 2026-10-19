#!/usr/bin/env python3
"""Inspect release PRs and merge only validated App-owned dev/staging releases."""
import argparse
import copy
import json
import os
import re
import subprocess
from pathlib import Path
import urllib.error
import urllib.request
import yaml

REPO = 'Local-Narx-Space/boutique-gitops'
SHA = re.compile(r'[a-f0-9]{40}')
BRANCH = re.compile(r'jenkins/promote/(dev|staging|production)/(frontend|catalogue|cart|orders)/[1-9][0-9]*')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('Authenticated redirect refused')


def validate_documents(before_values, after_values, before_chart, after_chart, service):
    expected = copy.deepcopy(before_values)
    image = after_values[service]['image']
    if (set(image) != {'repository', 'digest', 'tag'}
            or image['repository'] != f'ghcr.io/subhankar12-spec/boutique-{service}'
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', image['digest']) or image['tag'] != ''):
        raise ValueError('Automatic promotion requires the selected immutable service image')
    expected[service]['image'] = image
    if expected != after_values:
        raise ValueError('Automatic promotion cannot change other services or configuration')
    expected = copy.deepcopy(before_chart)
    old = [d for d in expected['dependencies'] if d.get('alias') == service]
    new = [d for d in after_chart['dependencies'] if d.get('alias') == service]
    if len(old) != 1 or len(new) != 1 or not re.fullmatch(r'0\.1\.0-[a-f0-9]{40}', new[0]['version']):
        raise ValueError('Automatic promotion requires a single source-pinned service chart')
    old[0]['version'] = new[0]['version']
    if expected != after_chart:
        raise ValueError('Automatic promotion cannot change chart policy or another dependency')


def validate_delta(root, target, service, head):
    def git(*args):
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
        if result.returncode:
            raise ValueError('Promotion Git history read failed')
        return result.stdout.strip()
    if git('rev-parse', 'HEAD') != head:
        raise ValueError('Candidate differs from the validated PR head')
    base = git('merge-base', 'origin/main', head)
    def document(revision, name):
        return yaml.safe_load(git('show', f'{revision}:environments/{target}/{name}'))
    validate_documents(document(base, 'releases.yaml'), document(head, 'releases.yaml'),
                       document(base, 'Chart.yaml'), document(head, 'Chart.yaml'), service)


def automatic_request(pr, head, files, bot, bot_id):
    match = BRANCH.fullmatch(pr.get('head', {}).get('ref', ''))
    if not match or match[1] == 'production':
        return None
    if pr.get('state') != 'open':
        return None
    inspect(pr, head)
    author = pr.get('user', {})
    if (pr.get('draft') or not re.fullmatch(r'[a-zA-Z0-9-]+\[bot\]', bot)
            or not re.fullmatch(r'[1-9][0-9]*', str(bot_id))
            or author.get('login') != bot or author.get('type') != 'Bot'
            or str(author.get('id')) != str(bot_id)):
        raise ValueError('Automatic release requires the configured App bot identity')
    target, service = match[1], match[2]
    allowed = re.compile(rf'environments/{target}/(?:Chart\.yaml|releases\.yaml|charts/boutique-{service}-[^/]+\.tgz)')
    if not files or len(files) != pr.get('changed_files'):
        raise ValueError('Incomplete promotion file list')
    names = []
    for file in files:
        for key in ('filename', 'previous_filename'):
            name = file.get(key)
            if key == 'filename' and not isinstance(name, str):
                raise ValueError('Missing promotion filename')
            if name is not None and (not isinstance(name, str) or not allowed.fullmatch(name)):
                raise ValueError('Automatic release cannot change code, configuration or another service')
        names.append(file['filename'])
    if len(set(names)) != len(names):
        raise ValueError('Duplicate promotion filenames')
    return {'target': target, 'service': service, 'head': head}


def merge(number, head, token, opener=None):
    if not re.fullmatch(r'[1-9][0-9]*', number) or not SHA.fullmatch(head) or not token:
        raise ValueError('Numeric PR, full validated head and scoped App token required')
    if opener is None:
        opener = urllib.request.build_opener(NoRedirect()).open
    request = urllib.request.Request(
        f'https://api.github.com/repos/{REPO}/pulls/{number}/merge',
        data=json.dumps({'sha': head, 'merge_method': 'squash'}).encode(), method='PUT',
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json', 'User-Agent': 'BoutiqueRelease/1.0'})
    try:
        with opener(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 405:
            raise ValueError('GitHub checks or conflicts block merging; rerun validation when ready') from None
        raise ValueError(f'GitHub refused automatic promotion (HTTP {error.code})') from None
    except (OSError, ValueError) as error:
        raise ValueError('Automatic promotion API request failed') from None
    if result.get('merged') is not True or not SHA.fullmatch(result.get('sha', '')):
        raise ValueError('GitHub did not confirm the exact promotion merge')
    return {'merged': True, 'commit': result['sha']}


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
    parser.add_argument('--auto-merge', action='store_true')
    parser.add_argument('--files', type=Path)
    parser.add_argument('--bot', default='')
    parser.add_argument('--bot-id', default='')
    parser.add_argument('--number', default='')
    parser.add_argument('--candidate', type=Path)
    args = parser.parse_args()
    try:
        pr = json.loads(Path(args.pr).read_text())
        if args.auto_merge:
            if not args.files or not re.fullmatch(r'[1-9][0-9]*', args.number):
                raise ValueError('PR number and complete files are required for automatic merging')
            # gh --paginate --slurp returns one array per API page.
            pages = json.loads(args.files.read_text())
            files = [file for page in pages for file in page]
            eligible = automatic_request(pr, args.head, files, args.bot, args.bot_id)
            result = {'merged': False}
            if eligible is not None:
                if args.candidate is None:
                    raise ValueError('Validated candidate checkout required')
                validate_delta(args.candidate, eligible['target'], eligible['service'], args.head)
                token = os.environ.get('GH_TOKEN', '')
                if not token:
                    raise ValueError('Scoped App token required')
                result = merge(args.number, args.head, token)
        else:
            result = inspect(pr, args.head)
    except yaml.YAMLError:
        raise SystemExit('Invalid release YAML; automatic promotion refused')
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as error:
        raise SystemExit(str(error))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
