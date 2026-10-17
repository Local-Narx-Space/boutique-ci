#!/usr/bin/env python3
"""Validate actual Declarative syntax using an authenticated Jenkins controller.

The controller must have the locked pipeline-model-definition plugin loaded.
Use a short-lived API token in a mode-0600 file; it is never printed. This checks
Declarative semantics, not agent availability or successful job execution.
"""
import argparse
import base64
import json
import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ValueError('Jenkins redirected the authenticated request; use its final URL')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--token-file', required=True, type=Path)
    parser.add_argument('files', type=Path, nargs='+')
    args = parser.parse_args()
    target = urllib.parse.urlsplit(args.url)
    if target.username or target.password or target.query or target.fragment:
        parser.error('Use a Jenkins URL without credentials/query/fragment')
    if target.scheme != 'https' and not (target.scheme == 'http' and target.hostname in {'127.0.0.1', 'localhost', '::1'}):
        parser.error('HTTPS is required except for loopback controllers')
    if args.token_file.stat().st_mode & 0o077:
        parser.error('Token file must have mode 0600 or stricter')
    token = args.token_file.read_text().strip()
    if not token or '\n' in token:
        parser.error('Token file must contain exactly one token')
    headers = {'Authorization': 'Basic ' + base64.b64encode(f'{args.user}:{token}'.encode()).decode(),
               'User-Agent': 'BoutiqueJenkinsClient/1.0', 'Accept': 'application/json'}
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    origin = args.url.rstrip('/')
    try:
        request = urllib.request.Request(origin + '/crumbIssuer/api/json', headers=headers)
        try:
            with opener.open(request, timeout=30) as response:
                crumb = json.load(response)
                headers[crumb['crumbRequestField']] = crumb['crumb']
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
        for path in args.files:
            source = path.read_text()
            body = urllib.parse.urlencode({'jenkinsfile': source}).encode()
            request = urllib.request.Request(origin + '/pipeline-model-converter/validate', data=body,
                                             headers={**headers, 'Content-Type': 'application/x-www-form-urlencoded'})
            with opener.open(request, timeout=60) as response:
                result = response.read(1024 * 1024).decode()
            if 'Jenkinsfile successfully validated.' not in result:
                print(f'{path}: {result.strip()}')
                parser.exit(1, 'Declarative validation failed\n')
            print(f'{path}: Declarative validation passed')
    except (OSError, ValueError, urllib.error.URLError) as exc:
        # No request headers, credentials or response bodies are exposed here.
        parser.exit(1, f'Controller validation unavailable: {type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()
