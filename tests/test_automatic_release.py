#!/usr/bin/env python3
"""Exercise automatic promotion authorization boundaries without GitHub credentials."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('automatic_release', Path(__file__).parents[1] / 'scripts/automatic-release.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Authorization(unittest.TestCase):
    def setUp(self):
        self.sha = 'a' * 40
        self.pr = {'state':'open','draft':False,'base':{'ref':'main'},
                   'head':{'ref':'jenkins/promote/dev/frontend/9','sha':self.sha,
                           'repo':{'full_name':module.REPO}},'user':{'login':'release-bot'}}
        self.paths = ['environments/dev/Chart.yaml','environments/dev/releases.yaml',
                      'environments/dev/charts/boutique-frontend-0.1.0-test.tgz']
    def call(self):
        return module.request(self.pr,'release-bot',self.sha,self.paths)
    def test_bot_dev_allowed(self):
        self.assertEqual(self.call()['target'],'dev')
    def test_bot_staging_allowed(self):
        self.pr['head']['ref']='jenkins/promote/staging/frontend/9'
        self.paths=[p.replace('/dev/','/staging/') for p in self.paths]
        self.assertEqual(self.call()['target'],'staging')
    def test_production_and_rollback_require_review(self):
        for branch in ['jenkins/promote/production/frontend/9','jenkins/rollback/dev/frontend/9','human-change']:
            self.pr['head']['ref']=branch
            self.assertIsNone(self.call())
    def test_invalid_metadata_rejected(self):
        original=copy.deepcopy(self.pr)
        cases=[('draft',True),('state','closed'),('user',{'login':'someone-else'}),
               ('base',{'ref':'other'}),('head',{**self.pr['head'],'sha':'b'*40}),
               ('head',{**self.pr['head'],'repo':{'full_name':'fork/repo'}})]
        for key,value in cases:
            self.pr=copy.deepcopy(original);self.pr[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.call()
    def test_configuration_and_other_service_changes_rejected(self):
        for path in ['pipelines/test','laptop-profiles/dev/values.yaml',
                     'environments/dev/templates/network.yaml',
                     'environments/dev/charts/boutique-orders-test.tgz',
                     'environments/production/releases.yaml']:
            self.paths=[path]
            with self.subTest(path=path),self.assertRaises(ValueError):self.call()
    def test_app_bot_requires_matching_app_identity(self):
        self.pr['user']={'login':'boutique-jenkins-bot[bot]','type':'Bot','id':343828366}
        self.assertEqual(module.request(self.pr,'boutique-jenkins-bot[bot]',self.sha,self.paths,343828366)['target'],'dev')
        for actor_id in [None, '', 1234]:
            self.pr['user']['id']=actor_id
            with self.subTest(actor_id=actor_id), self.assertRaises(ValueError):
                module.request(self.pr,'boutique-jenkins-bot[bot]',self.sha,self.paths,343828366)
        self.pr['user']['id']=343828366
        self.pr['user']['type']='User'
        with self.assertRaises(ValueError):
            module.request(self.pr,'boutique-jenkins-bot[bot]',self.sha,self.paths,343828366)

    def test_empty_diff_rejected(self):
        self.paths=[]
        with self.assertRaises(ValueError):self.call()

if __name__=='__main__':unittest.main()
