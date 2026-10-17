pipeline {
    agent { label 'trusted-release' }
    options { timestamps(); timeout(time: 40, unit: 'MINUTES'); disableConcurrentBuilds(); skipDefaultCheckout(true) }
    parameters { string(name: 'PR_NUMBER', defaultValue: '', description: 'GitOps PR number to validate') }
    // Bind validated request parameters explicitly, including the first triggered build.
    environment {
        PR_NUMBER = "${params.PR_NUMBER}"
    }
    stages {
        stage('Validate request') {
            steps { script {
                if (env.BOUTIQUE_CONTROLLER_ROLE != 'release' || !(params.PR_NUMBER ==~ /[1-9][0-9]*/)) { error('Reviewed controller and numeric PR required') }
                env.GITOPS_PR_CREDENTIAL = env.BOUTIQUE_GITOPS_PR_CREDENTIAL ?: 'gitops-pr'
                env.GITOPS_BOT_LOGIN = env.BOUTIQUE_GITOPS_BOT_LOGIN ?: ''
                env.GITOPS_APP_ID = env.BOUTIQUE_GITOPS_APP_ID ?: ''
                env.GITOPS_BOT_ID = env.BOUTIQUE_GITOPS_BOT_ID ?: ''
                if (env.GITOPS_PR_CREDENTIAL == 'gitops-release-app' &&
                    (!(env.GITOPS_BOT_LOGIN ==~ /[a-zA-Z0-9-]+\[bot\]/) || !(env.GITOPS_APP_ID ==~ /[1-9][0-9]*/) || !(env.GITOPS_BOT_ID ==~ /[1-9][0-9]*/))) {
                    error('Configure the expected App bot login, numeric actor ID and App ID before selecting its credential')
                }
            } }
        }
        stage('Fetch protected tools and PR revision') {
            steps {
                deleteDir()
                dir('automation') { checkout([$class: 'GitSCM', branches: [[name: 'main']], userRemoteConfigs: [[url: 'https://github.com/subhankar12-spec/boutique-ci.git', credentialsId: 'github-read']]]) }
                dir('tools') { checkout([$class: 'GitSCM', branches: [[name: 'main']], userRemoteConfigs: [[url: 'https://github.com/subhankar12-spec/boutique-gitops.git', credentialsId: 'github-read']]]) }
                withCredentials([string(credentialsId: 'gitops-checks', variable: 'GH_TOKEN')]) {
                    sh '''set +x
                        set -eu
                        gh api "repos/subhankar12-spec/boutique-gitops/pulls/$PR_NUMBER" > pr.json
                    '''
                }
                script {
                    // Parse on the agent without requiring Groovy constructor/method approvals.
                    env.PR_HEAD_SHA = sh(returnStdout: true, script: '''python3 - <<'PR'
import json
import re
from pathlib import Path

try:
    pr = json.loads(Path('pr.json').read_text())
    sha = pr['head']['sha']
    valid = (pr['state'] == 'open' and pr['base']['ref'] == 'main'
             and pr['head']['repo']['full_name'] == 'subhankar12-spec/boutique-gitops'
             and isinstance(sha, str) and re.fullmatch(r'[a-f0-9]{40}', sha))
except (ValueError, KeyError, TypeError):
    valid = False
if not valid:
    raise SystemExit('Expected an open same-repository GitOps PR against main')
print(sha)
PR
''').trim()
                }
                dir('candidate') { checkout([$class: 'GitSCM', branches: [[name: env.PR_HEAD_SHA]], userRemoteConfigs: [[url: 'https://github.com/subhankar12-spec/boutique-gitops.git', credentialsId: 'github-read']]]) }
            }
        }
        stage('Validate Helm and manifests') {
            steps {
                withCredentials([string(credentialsId: 'gitops-checks', variable: 'GH_TOKEN')]) {
                    sh '''set +x
                        gh api --method POST "repos/subhankar12-spec/boutique-gitops/statuses/$PR_HEAD_SHA" -f state=pending -f context='boutique/gitops-validation' -f description='Validating Helm and Kubernetes manifests' -f target_url="$BUILD_URL" >/dev/null
                    '''
                }
                // Use protected scripts; candidate files are Helm/configuration inputs.
                // No shell/Jenkinsfile from the PR is executed; no API token is bound here.
                sh 'bash tools/scripts/validate.sh "$WORKSPACE/candidate" origin/main'
            }
        }
        stage('Report successful validation') {
            steps {
                withCredentials([string(credentialsId: 'gitops-checks', variable: 'GH_TOKEN')]) {
                    sh '''set +x
                        set -eu
                        CURRENT_HEAD=$(gh api "repos/subhankar12-spec/boutique-gitops/pulls/$PR_NUMBER" --jq .head.sha)
                        test "$CURRENT_HEAD" = "$PR_HEAD_SHA"
                        gh api --method POST "repos/subhankar12-spec/boutique-gitops/statuses/$PR_HEAD_SHA" -f state=success -f context='boutique/gitops-validation' -f description='Helm and Kubernetes manifests passed' -f target_url="$BUILD_URL" >/dev/null
                    '''
                }
            }
        }
        stage('Queue human-reviewed production merge watcher') {
            when { expression { env.BOUTIQUE_RELEASE_AUTOMATION == 'true' } }
            steps { script {
                def production = sh(returnStdout: true, script: '''python3 - <<'PRODUCTION'
import json
import re
from pathlib import Path
pr = json.loads(Path('pr.json').read_text())
print('yes' if re.fullmatch(r'jenkins/promote/production/(frontend|catalogue|cart|orders)/[1-9][0-9]*', pr['head']['ref']) else 'no')
PRODUCTION
''').trim()
                if (production == 'yes') {
                    build job: 'boutique-production-verify', wait: false, parameters: [
                        string(name: 'PR_NUMBER', value: params.PR_NUMBER),
                        string(name: 'PR_HEAD_SHA', value: env.PR_HEAD_SHA)
                    ]
                }
            } }
        }
        stage('Merge validated dev or staging promotion') {
            when { expression { env.BOUTIQUE_RELEASE_AUTOMATION == 'true' } }
            steps {
                withCredentials([usernamePassword(credentialsId: env.GITOPS_PR_CREDENTIAL, usernameVariable: 'GIT_USER', passwordVariable: 'GH_TOKEN')]) {
                    sh '''set +x
                        set -eu
                        gh api "repos/subhankar12-spec/boutique-gitops/pulls/$PR_NUMBER" > current-pr.json
                        if [ -n "$GITOPS_APP_ID" ]; then
                            test "$GIT_USER" = "$GITOPS_APP_ID"
                            BOT="$GITOPS_BOT_LOGIN"
                        else
                            BOT=$(gh api user --jq .login)
                        fi
                        set -- --pr current-pr.json --bot "$BOT" --head "$PR_HEAD_SHA" --candidate candidate
                        if [ -n "$GITOPS_APP_ID" ]; then set -- "$@" --bot-id "$GITOPS_BOT_ID"; fi
                        python3 automation/scripts/automatic-release.py "$@" > automatic-release.json
                        if [ "$(cat automatic-release.json)" = null ]; then
                            echo 'Human-reviewed change: automatic merge skipped.'
                            exit 0
                        fi
                        # GitHub enforces branch protections; never use admin bypass.
                        gh api --method PUT "repos/subhankar12-spec/boutique-gitops/pulls/$PR_NUMBER/merge" -f sha="$PR_HEAD_SHA" -f merge_method=squash > merge.json
                        python3 - <<'MERGE'
import json
from pathlib import Path
result = json.loads(Path('merge.json').read_text())
if result.get('merged') is not True:
    raise SystemExit('GitHub did not merge the validated promotion')
import re
sha = result.get('sha', '')
if not re.fullmatch(r'[a-f0-9]{40}', sha):
    raise SystemExit('Missing merge commit SHA')
Path('merge-sha.txt').write_text(sha)
MERGE
                    '''
                }
                script {
                    if (fileExists('merge-sha.txt')) {
                        env.AUTO_MERGE_SHA = readFile('merge-sha.txt').trim()
                        env.AUTO_TARGET = sh(returnStdout: true, script: '''python3 -c "import json; print(json.load(open('automatic-release.json'))['target'])"''').trim()
                        env.AUTO_SERVICE = sh(returnStdout: true, script: '''python3 -c "import json; print(json.load(open('automatic-release.json'))['service'])"''').trim()
                        env.AUTO_IMAGE = sh(returnStdout: true, script: '''python3 - "$AUTO_SERVICE" "$AUTO_TARGET" <<'IMAGE'
import sys
sys.path.insert(0, 'tools/scripts')
from release_config import selected_image
from pathlib import Path
print(selected_image(Path.cwd() / 'candidate', sys.argv[1], sys.argv[2]))
IMAGE
''').trim()
                    }
                }
            }
        }
        stage('Queue deployed release verification') {
            when { expression { env.AUTO_MERGE_SHA } }
            steps {
                // Release the executor before verification waits for Argo.
                build job: (env.AUTO_TARGET == 'dev' ? 'boutique-deploy-dev' : 'boutique-deploy-qa'), wait: false, parameters: [
                    string(name: 'ACTION', value: 'verify'),
                    string(name: 'TARGET', value: env.AUTO_TARGET),
                    string(name: 'SERVICE', value: env.AUTO_SERVICE),
                    string(name: 'IMAGE', value: env.AUTO_IMAGE),
                    string(name: 'GITOPS_COMMIT', value: env.AUTO_MERGE_SHA)
                ]
            }
        }
    }
    post {
        unsuccessful {
            script {
                if (env.PR_HEAD_SHA ==~ /[a-f0-9]{40}/) {
                    withCredentials([string(credentialsId: 'gitops-checks', variable: 'GH_TOKEN')]) {
                        sh returnStatus: true, script: '''set +x
                            gh api --method POST "repos/subhankar12-spec/boutique-gitops/statuses/$PR_HEAD_SHA" -f state=failure -f context='boutique/gitops-validation' -f description='Manifest validation failed; inspect Jenkins' -f target_url="$BUILD_URL" >/dev/null
                        '''
                    }
                }
            }
        }
    }
}
