#!/usr/bin/env python3
"""Find reusable artifacts from a successful main push for the exact tag commit."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


def pages(get, path, key):
    page = 1
    separator = '&' if '?' in path else '?'
    while True:
        values = get(f'{path}{separator}per_page=100&page={page}').get(key)
        if not isinstance(values, list):
            raise RuntimeError('Unexpected GitHub API response')
        yield from values
        if len(values) < 100:
            return
        page += 1


def select_build(get, sha):
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Source SHA must be a full commit hash')
    query = urllib.parse.urlencode({'branch': 'main', 'event': 'push',
                                   'status': 'success', 'head_sha': sha})
    for run in pages(get, 'actions/workflows/build-package.yml/runs?' + query, 'workflow_runs'):
        if (run.get('head_sha') != sha or run.get('head_branch') != 'main'
                or run.get('event') != 'push' or run.get('status') != 'completed'
                or run.get('conclusion') != 'success'):
            continue
        run_id = run.get('id')
        if type(run_id) is not int or run_id <= 0:
            continue
        artifacts = list(pages(get, f'actions/runs/{run_id}/artifacts', 'artifacts'))
        selected = {}
        for name, output in [('router-watchdog-ipk', 'ipk_artifact_id'),
                             ('router-watchdog-feed', 'feed_artifact_id')]:
            matches = [item for item in artifacts
                       if item.get('name') == name and item.get('expired') is False]
            if len(matches) != 1 or type(matches[0].get('id')) is not int or matches[0]['id'] <= 0:
                break
            selected[output] = matches[0]['id']
        if len(selected) == 2:
            return {'run_id': run_id, **selected}
    raise RuntimeError('No successful main push build with both nonexpired artifacts exists '
                       'for the tag commit. Build that commit on main, then rerun this release; '
                       'no older commit or automatic rebuild will be used')


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository name')
    token = os.environ['GITHUB_TOKEN']
    api = os.environ.get('GITHUB_API_URL', 'https://api.github.com').rstrip('/')

    def get(path):
        request = urllib.request.Request(f'{api}/repos/{repository}/{path}', headers={
            'Accept': 'application/vnd.github+json', 'Authorization': f'Bearer {token}',
            'X-GitHub-Api-Version': '2022-11-28',
        })
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise RuntimeError(f'GitHub API request failed with HTTP {exc.code}') from None
        except urllib.error.URLError:
            raise RuntimeError('GitHub API is unavailable') from None

    selected = select_build(get, os.environ['SOURCE_SHA'])
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as handle:
        for key, value in selected.items():
            handle.write(f'{key}={value}\n')
    print(f"Reusing successful main build {selected['run_id']} for {os.environ['SOURCE_SHA']}")


if __name__ == '__main__':
    main()
