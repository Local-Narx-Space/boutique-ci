#!/usr/bin/env python3
"""Render a pinned, namespace-scoped Rollouts controller; never apply resources."""
import argparse
import hashlib
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent


def documents(name):
    lock = json.loads((ROOT / 'release-lock.json').read_text())
    source = (ROOT / name).read_bytes()
    if hashlib.sha256(source).hexdigest() != lock['assets'][name]:
        raise ValueError('Upstream manifest differs from the reviewed release lock')
    return [item for item in yaml.safe_load_all(source) if item]


def controller(namespace):
    image = json.loads((ROOT / 'release-lock.json').read_text())['controllerImage']
    for item in documents('namespace-install.yaml'):
        # Namespace installation also ships aggregate ClusterRoles. Do not grant
        # cluster-wide permissions or change existing admin/edit/view aggregation.
        if item['kind'] == 'ClusterRole':
            continue
        item['metadata']['namespace'] = namespace
        if item['kind'] == 'Deployment':
            container = item['spec']['template']['spec']['containers'][0]
            container['image'] = image
            container['imagePullPolicy'] = 'IfNotPresent'
            container['resources'] = {'requests': {'cpu': '50m', 'memory': '96Mi'},
                                      'limits': {'cpu': '500m', 'memory': '256Mi', 'ephemeral-storage': '256Mi'}}
        yield item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace')
    parser.add_argument('--crds', action='store_true')
    args = parser.parse_args()
    if args.crds:
        output = [item for item in documents('install.yaml') if item['kind'] == 'CustomResourceDefinition']
    elif args.namespace:
        output = list(controller(args.namespace))
    else:
        parser.error('Select --crds or --namespace')
    print(yaml.safe_dump_all(output, sort_keys=False), end='')


if __name__ == '__main__':
    main()
