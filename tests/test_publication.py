"""Exercise the actual publication shell without credentials or registry access."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'vars/servicePipeline.groovy').read_text()
PUBLISH = re.search(r"stage\('Publish tested artifact'\).*?sh '''(.*?)'''", SOURCE, re.S).group(1)
STUB = '''#!/usr/bin/env python3
import os,sys
from pathlib import Path
name=Path(sys.argv[0]).name
args=sys.argv[1:]
scenario=os.environ['SCENARIO']
if args[0]=='logout' or args[:2]==['registry','logout']:
    raise SystemExit(0)
if args[0]=='login' or args[:2]==['registry','login']:
    sys.stdin.read()
    raise SystemExit(0)
if name=='docker' and args[:2]==['manifest','inspect']:
    if scenario=='image_exists':raise SystemExit(0)
    print('network timeout' if scenario=='image_error' else 'manifest unknown',file=sys.stderr)
    raise SystemExit(1)
if name=='helm' and args[:2]==['show','chart']:
    if scenario=='chart_exists':raise SystemExit(0)
    print('network timeout' if scenario=='chart_error' else 'manifest unknown',file=sys.stderr)
    raise SystemExit(1)
if args[0]=='push':
    with open(os.environ['PUSH_LOG'],'a') as out:out.write(name+'\\n')
    raise SystemExit(0)
if name=='docker' and args[0]=='inspect':
    print('ghcr.io/subhankar12-spec/boutique-frontend@sha256:'+'a'*64)
    raise SystemExit(0)
raise SystemExit('Unexpected tool invocation')
'''


class PublicationTests(unittest.TestCase):
    def run_publication(self, scenario):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            binaries=root/'bin'
            binaries.mkdir()
            for name in ['docker','helm']:
                path=binaries/name
                path.write_text(STUB)
                path.chmod(0o755)
            env={**os.environ,'PATH':str(binaries)+os.pathsep+os.environ['PATH'],
                 'WORKSPACE':directory,'REGISTRY':'ghcr.io','GITHUB_OWNER':'subhankar12-spec',
                 'SERVICE':'frontend','SOURCE_COMMIT':'a'*40,'REGISTRY_USER':'fixture',
                 'REGISTRY_TOKEN':'fixture','IMAGE_TAG':'fixture-image',
                 'SCENARIO':scenario,'PUSH_LOG':str(root/'pushes')}
            result=subprocess.run(['bash','-c',PUBLISH],cwd=root,env=env,capture_output=True,text=True)
            pushes=(root/'pushes').read_text().splitlines() if (root/'pushes').exists() else []
            return result,pushes

    def test_existing_image_is_never_overwritten(self):
        result,pushes=self.run_publication('image_exists')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(pushes,[])

    def test_unknown_image_registry_error_blocks_publication(self):
        result,pushes=self.run_publication('image_error')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(pushes,[])

    def test_existing_chart_is_never_overwritten(self):
        result,pushes=self.run_publication('chart_exists')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(pushes,[])

    def test_unknown_chart_registry_error_blocks_publication(self):
        result,pushes=self.run_publication('chart_error')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(pushes,[])

    def test_confirmed_missing_artifacts_publish_both_image_and_chart(self):
        result,pushes=self.run_publication('missing')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(pushes,['docker','helm'])


if __name__ == '__main__':
    unittest.main()
