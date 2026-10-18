#!/usr/bin/env python3
"""Derive strict local kubeconform schemas from the checksum-locked CRDs."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('rollouts_controller', ROOT / 'render-controller.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def strict_schema(value):
    if isinstance(value, list):
        return [strict_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: strict_schema(item) for key, item in value.items()}
    if result.get('x-kubernetes-int-or-string') or result.get('format') == 'int-or-string':
        result.pop('type', None)
        result.pop('format', None)
        result['oneOf'] = [{'type': 'integer'}, {'type': 'string'}]
    if 'properties' in result and not result.get('x-kubernetes-preserve-unknown-fields'):
        result.setdefault('additionalProperties', False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    for crd in renderer.documents('install.yaml'):
        if crd['kind'] != 'CustomResourceDefinition':
            continue
        for version in crd['spec']['versions']:
            if not version.get('served'):
                continue
            schema = strict_schema(copy.deepcopy(version['schema']['openAPIV3Schema']))
            name = (crd['spec']['names']['kind'] + '_' + version['name']).lower() + '.json'
            (args.destination / name).write_text(json.dumps(schema) + '\n')


if __name__ == '__main__':
    main()
