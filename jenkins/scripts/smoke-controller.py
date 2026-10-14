#!/usr/bin/env python3
"""Boot the locked Jenkins runtime and test configuration on loopback.

Requires Java 21 and a cache outside the checkout. Official SHA256s are checked
before launch. No GitHub/cloud credentials are inherited, no SCM jobs are
created/indexed, and no application deployment is attempted. Controller home
and ephemeral credentials are removed at shutdown; public reports/logs remain.
"""
import argparse
import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path, help='Private artifact cache outside the checkout')
    parser.add_argument('--port', type=int, default=8099)
    args = parser.parse_args()
    cache = args.directory.resolve()
    if cache == ROOT or cache.is_relative_to(ROOT):
        parser.error('Use an artifact cache outside the repository')
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged TCP port')
    if not shutil.which('java'):
        parser.error('Java 21 is required')
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', args.port))
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    if cache.stat().st_mode & 0o077:
        parser.error('Cache directory must have mode 0700 or stricter')
    plugins = cache / 'plugins'
    subprocess.run(['python3', str(ROOT / 'jenkins/scripts/install-locked-plugins.py'), '--directory', str(plugins),
                    '--include-core', '--workers', '8'], check=True)
    lock = json.loads((ROOT / 'jenkins/controller/plugins.lock.json').read_text())
    runtime = Path(tempfile.mkdtemp(prefix='controller-', dir=cache))
    home = runtime / 'home'
    home.mkdir(mode=0o700)
    (home / 'plugins').mkdir()
    for row in lock['plugins']:
        shutil.copyfile(plugins / (row['name'] + '.jpi'), home / 'plugins' / (row['name'] + '.jpi'))
    password = home / '.startup-password'
    password.write_text(secrets.token_urlsafe(48))
    password.chmod(0o600)
    initialization = home / 'init.groovy.d'
    initialization.mkdir()
    (initialization / 'isolated-security.groovy').write_text('''import jenkins.model.Jenkins
import hudson.security.HudsonPrivateSecurityRealm
import hudson.security.FullControlOnceLoggedInAuthorizationStrategy
import jenkins.security.ApiTokenProperty

def instance=Jenkins.get()
instance.setNumExecutors(0)
def realm=new HudsonPrivateSecurityRealm(false)
def passwordFile=new File(instance.rootDir,'.startup-password')
def user=realm.createAccount('validation-admin',passwordFile.text.trim())
instance.setSecurityRealm(realm)
def strategy=new FullControlOnceLoggedInAuthorizationStrategy()
strategy.setAllowAnonymousRead(false)
instance.setAuthorizationStrategy(strategy)
instance.save()
def value=user.getProperty(ApiTokenProperty.class).tokenStore.generateNewToken('isolated-runtime-check').plainValue
user.save()
def tokenFile=new File(instance.rootDir,'.linter-token')
tokenFile.text=value+'\\n'
tokenFile.setReadable(false,false); tokenFile.setReadable(true,true)
tokenFile.setWritable(false,false); tokenFile.setWritable(true,true)
passwordFile.delete()
''')
    origin = f'http://127.0.0.1:{args.port}'
    report = {'jenkinsVersion': lock['jenkinsVersion'], 'plugins': len(lock['plugins']), 'passed': False}
    process = None
    with (runtime / 'controller.log').open('w') as log:
        try:
            process = subprocess.Popen(['java', '-Xmx512m', '-Djenkins.install.runSetupWizard=false',
                                        '-Dhudson.model.UpdateCenter.never=true', '-jar', str(cache / 'jenkins.war'),
                                        '--httpListenAddress=127.0.0.1', f'--httpPort={args.port}',
                                        f'--webroot={runtime / "webroot"}'],
                                       env={'PATH': os.environ['PATH'], 'JENKINS_HOME': str(home)},
                                       stdout=log, stderr=subprocess.STDOUT)
            token_file = home / '.linter-token'
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError('Jenkins exited during initialization; inspect the private controller log')
                if token_file.exists():
                    break
                time.sleep(.5)
            else:
                raise RuntimeError('Jenkins startup exceeded 60 seconds')
            credentials = base64.b64encode(('validation-admin:' + token_file.read_text().strip()).encode()).decode()
            headers = {'Authorization': 'Basic ' + credentials}

            def request(path, data=None, content_type=None):
                current_headers = {**headers}
                if content_type:
                    current_headers['Content-Type'] = content_type
                req = urllib.request.Request(origin + path, data=data, headers=current_headers)
                # The server is a fresh process bound to loopback; no redirects are followed with credentials.
                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, *unused):
                        raise RuntimeError('Unexpected authenticated redirect')
                with urllib.request.build_opener(NoRedirect()).open(req, timeout=60) as response:
                    return response.read()

            def groovy(source):
                body = urllib.parse.urlencode({'script': source}).encode()
                return request('/scriptText', body, 'application/x-www-form-urlencoded').decode()

            active = json.loads(request('/pluginManager/api/json?tree=plugins%5BshortName,version,active,enabled%5D'))['plugins']
            expected = {row['name']: row['version'] for row in lock['plugins']}
            actual = {row['shortName']: row['version'] for row in active if row['active'] and row['enabled']}
            if actual != expected:
                raise RuntimeError('Loaded plugin set differs from the verified lock')
            print(f'Jenkins {lock["jenkinsVersion"]}: all {len(active)} locked plugins active')

            yaml = (ROOT / 'jenkins/casc/jenkins.yaml').read_text()
            values = {'JENKINS_ADMIN_USER': 'validation-admin', 'JENKINS_ADMIN_PASSWORD': 'isolated-schema-placeholder',
                      'JENKINS_PLATFORM_ADMIN_PASSWORD': secrets.token_urlsafe(32),
                      'BOUTIQUE_CONTROLLER_ROLE': 'release', 'JENKINS_URL': origin + '/', 'BOUTIQUE_CI_LIBRARY_REF': '1' * 40,
                      'BOUTIQUE_DEV_ORIGIN': 'https://dev.boutique.test:8443',
                      'BOUTIQUE_STAGING_ORIGIN': 'https://staging.boutique.test:8443',
                      'BOUTIQUE_PRODUCTION_ORIGIN': 'https://production.boutique.test:9443'}
            for key, value in values.items():
                yaml = yaml.replace('${' + key + '}', value)
            encoded = base64.b64encode(yaml.encode()).decode()
            result = groovy('''import io.jenkins.plugins.casc.ConfigurationAsCode
import io.jenkins.plugins.casc.yaml.YamlSource
String yaml=new String(''' + json.dumps(encoded) + '''.decodeBase64(),'UTF-8')
def warnings=ConfigurationAsCode.get().checkWith(YamlSource.of(new ByteArrayInputStream(yaml.getBytes('UTF-8'))))
println('JCasC_CHECK_PASSED warnings='+warnings.size())
warnings.values().each { println(it) }
''')
            (runtime / 'jcasc-check.txt').write_text(result)
            if 'JCasC_CHECK_PASSED' not in result:
                raise RuntimeError('JCasC validation failed; inspect jcasc-check.txt')
            print(result.strip())

            role_paths = {role: str(ROOT / 'jenkins/jobs/release.groovy') for role in ('release', 'release-with-incident')}
            result = groovy('''import javaposse.jobdsl.plugin.JenkinsJobManagement
import javaposse.jobdsl.plugin.SandboxDslScriptLoader
import org.jenkinsci.plugins.workflow.job.WorkflowJob
import org.jenkinsci.plugins.scriptsecurity.scripts.ScriptApproval
import javaposse.jobdsl.dsl.Item
import jenkins.model.Jenkins
class DryRunJobManagement extends JenkinsJobManagement {
 Map<String,String> generated=[:]
 DryRunJobManagement(boolean incident) { super(System.out,[suppressAutomaticBuilds:true,enableIncidentBridgeBuild:incident],new File('.')); setFailOnMissingPlugin(true) }
 @Override boolean createOrUpdateConfig(Item item, boolean ignoreExisting) { generated[item.name]=item.xml; return true }
 @Override void queueJob(String name) { throw new IllegalStateException('SCM/build scheduling is forbidden in this dry run') }
}
def roles=new groovy.json.JsonSlurper().parseText(''' + json.dumps(json.dumps(role_paths)) + ''')
assert ScriptApproval.get().approvedSignatures.length == 0
def seed=Jenkins.get().createProject(WorkflowJob,'isolated-sandbox-seed')
roles.each { role,path ->
 def management=new DryRunJobManagement(role=='release-with-incident')
 new SandboxDslScriptLoader(management,seed).runScript(new File(path).text)
 management.generated.each { name,xml ->
  def document=new XmlParser(false,false).parseText(xml)
  def source=document.sources.data.'jenkins.branch.BranchSource'.source
  if(source.size()) {
   def branch=Jenkins.XSTREAM2.fromXML(groovy.xml.XmlUtil.serialize(document.sources.data.'jenkins.branch.BranchSource'[0]))
   def properties=branch.strategy.getPropertiesFor(new jenkins.scm.api.SCMHead('main'))
   assert properties.find { it.class.simpleName=='NoTriggerBranchProperty' }?.triggeredBranchesRegex == '^$': 'Bootstrap must suppress automatic builds'
   def original=source[0]
   def type=original.attribute('class')
   original.attributes().remove('class')
   def node=new groovy.util.Node(null,type,original.attributes(),original.value())
   def scm=Jenkins.XSTREAM2.fromXML(groovy.xml.XmlUtil.serialize(node))
   def traits=scm.traits.collect { it.class.simpleName }
   assert traits.contains('BranchDiscoveryTrait'): role+' source does not discover branches: '+name
   assert !traits.contains('ForkPullRequestDiscoveryTrait'): role+' source unexpectedly discovers fork PRs: '+name
   if(role.startsWith('release')) {
    assert !traits.contains('OriginPullRequestDiscoveryTrait'): 'Release source discovers PRs: '+name
    def filter=scm.traits.find { it.class.simpleName=='WildcardSCMHeadFilterTrait' }
    assert filter && filter.includes=='main' && filter.excludes=='': 'Release source is not restricted to main: '+name
   }
  }
 }
 assert management.generated.size() == (role=='release' ? 9 : 10): 'Unexpected job count'
 assert management.generated.containsKey('boutique-platform') == (role=='release-with-incident'): 'Adapter build must be opt-in'
 assert ScriptApproval.get().approvedSignatures.length == 0
 println('JOBDSL_CHECK_PASSED '+role+' count='+management.generated.size()+' sandbox=true approvals=0')
}
''')
            (runtime / 'job-dsl-check.txt').write_text(result)
            if 'JOBDSL_CHECK_PASSED release count=9' not in result or 'JOBDSL_CHECK_PASSED release-with-incident count=10' not in result:
                raise RuntimeError('JobDSL validation failed; inspect job-dsl-check.txt')
            print(result.strip())
            report['jobDslGeneratedJobs'] = {'default': 9, 'withIncidentBridge': 10}
            report['jobDslSandbox'] = True
            report['jobDslCustomMethodApprovals'] = 0

            source = (ROOT / 'vars/servicePipeline.groovy').read_text()
            body = source[source.index('    pipeline {'):source.rfind('\n}')]
            reference = runtime / 'service-reference.Jenkinsfile'
            reference.write_text("def config=[service:'frontend']\ndef isRelease={false}\n" + body + '\n')
            files = [reference, *sorted((ROOT / 'pipelines').glob('*.Jenkinsfile')),
                     ROOT.parent / 'boutique-infrastructure/Jenkinsfile',
                     ROOT.parent / 'boutique-gitops/Jenkinsfile']
            files = [path for path in files if path.exists()]
            subprocess.run(['python3', str(ROOT / 'jenkins/scripts/validate-pipelines.py'), '--url', origin,
                            '--user', 'validation-admin', '--token-file', str(token_file), *map(str, files)], check=True)
            report['declarativeFiles'] = [path.name for path in files]

            def create_job(name, script):
                definition = ET.Element('flow-definition')
                ET.SubElement(definition, 'description').text = 'Isolated coordination check: no SCM, agents or deployment'
                node = ET.SubElement(definition, 'definition', {'class': 'org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition'})
                ET.SubElement(node, 'sandbox').text = 'true'
                ET.SubElement(node, 'script').text = script
                request('/createItem?name=' + name, ET.tostring(definition), 'application/xml')

            create_job('isolated-verification-check', """pipeline {
 agent none
 parameters { booleanParam(name:'FAIL_CHECK', defaultValue:false) }
 stages {
  stage('Verify') { steps { script {
   if(params.FAIL_CHECK) { error('Intentional isolated verification failure') }
   echo 'Isolated verification passed'
  } } }
 }
}""")
            create_job('isolated-runtime-check', """pipeline {
 agent none
 options { timeout(time:2,unit:'MINUTES') }
 parameters { booleanParam(name:'FAIL_CHECK', defaultValue:false) }
 stages {
  stage('Downstream verification') { steps {
   build job:'isolated-verification-check', wait:true, propagate:true,
    parameters:[booleanParam(name:'FAIL_CHECK',value:params.FAIL_CHECK)]
  } }
 }
}""")
            report['runtimeBuilds'] = []
            for number, failure, expected_result in [(1, False, 'SUCCESS'), (2, True, 'FAILURE')]:
                # Parameter metadata is populated by the first Declarative execution.
                endpoint = 'build' if number == 1 else 'buildWithParameters'
                body = urllib.parse.urlencode({'FAIL_CHECK': str(failure).lower()}).encode()
                request('/job/isolated-runtime-check/' + endpoint, body, 'application/x-www-form-urlencoded')
                for _ in range(120):
                    try:
                        build = json.loads(request(f'/job/isolated-runtime-check/{number}/api/json?tree=number,result,building'))
                        if not build['building']:
                            if build['result'] != expected_result:
                                raise RuntimeError('Parent/downstream verification returned an unexpected result')
                            report['runtimeBuilds'].append(build)
                            print(f'Parent/downstream verification #{number}: {build["result"]}')
                            break
                    except urllib.error.HTTPError as exc:
                        if exc.code != 404:
                            raise
                    time.sleep(.5)
                else:
                    raise RuntimeError('Isolated Declarative build exceeded 60 seconds')
            # This local executor exists only in the disposable fixture controller.
            # The production JCasC was validated with zero built-in executors above.
            groovy('jenkins.model.Jenkins.get().setNumExecutors(1)')
            create_job('isolated-test-gate', """pipeline {
 agent any
 options { skipStagesAfterUnstable() }
 parameters {
  booleanParam(name:'FAIL_TEST', defaultValue:false)
  booleanParam(name:'REPORT_ONLY_FAILURE', defaultValue:false)
 }
 stages {
  stage('Test') {
   steps { script {
    def failure=params.FAIL_TEST ? '<failure message="intentional failure"/>' : ''
    writeFile file:'test-reports/junit.xml', text:'<testsuite name="fixture" tests="1"><testcase name="gate">'+failure+'</testcase></testsuite>'
    if(params.FAIL_TEST && !params.REPORT_ONLY_FAILURE) { error('Intentional test runner nonzero exit') }
   } }
   post { always { junit testResults:'test-reports/*.xml', allowEmptyResults:false, skipPublishingChecks:true } }
  }
  stage('Build image') { steps { echo 'SIMULATED_BUILD_REACHED' } }
  stage('Publish') { steps { echo 'SIMULATED_PUBLICATION_REACHED' } }
 }
}""")
            report['testGateBuilds'] = []
            for number, failure, report_only in [(1, False, False), (2, True, False), (3, True, True)]:
                endpoint = 'build' if number == 1 else 'buildWithParameters'
                body = urllib.parse.urlencode({'FAIL_TEST': str(failure).lower(), 'REPORT_ONLY_FAILURE': str(report_only).lower()}).encode()
                request('/job/isolated-test-gate/' + endpoint, body, 'application/x-www-form-urlencoded')
                for _ in range(120):
                    try:
                        build = json.loads(request(f'/job/isolated-test-gate/{number}/api/json?tree=number,result,building'))
                        if not build['building']:
                            expected = 'UNSTABLE' if report_only else ('FAILURE' if failure else 'SUCCESS')
                            if build['result'] != expected:
                                raise RuntimeError('Test gate returned unexpected build result')
                            tests = json.loads(request(f'/job/isolated-test-gate/{number}/testReport/api/json?tree=failCount,passCount,skipCount'))
                            if sum(tests[key] for key in ('passCount', 'failCount', 'skipCount')) != 1 or tests['failCount'] != int(failure):
                                raise RuntimeError('JUnit results were not recorded correctly')
                            console = request(f'/job/isolated-test-gate/{number}/consoleText').decode()
                            reached = 'SIMULATED_PUBLICATION_REACHED' in console
                            if reached == failure or ('SIMULATED_BUILD_REACHED' in console) == failure:
                                raise RuntimeError('Failed tests did not block build/publication')
                            report['testGateBuilds'].append({'result':build['result'], 'tests':tests, 'publicationReached':reached})
                            print(f'JUnit test gate #{number}: {build["result"]}; publication reached={reached}')
                            break
                    except urllib.error.HTTPError as exc:
                        if exc.code != 404:
                            raise
                    time.sleep(.5)
                else:
                    raise RuntimeError('JUnit fixture exceeded 60 seconds')
            report['passed'] = True
            print('Isolated Declarative execution passed; application pipelines/deployments were not executed')
        finally:
            if process:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            (runtime / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            shutil.rmtree(home)
            shutil.rmtree(runtime / 'webroot', ignore_errors=True)
            print(f'Public runtime report: {runtime / "report.json"}; temporary credentials removed')


if __name__ == '__main__':
    main()
