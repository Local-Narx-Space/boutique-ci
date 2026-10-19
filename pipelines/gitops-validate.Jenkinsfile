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
                dir('automation') { checkout([$class: 'GitSCM', branches: [[name: 'main']], userRemoteConfigs: [[url: 'https://github.com/Local-Narx-Space/boutique-ci.git', credentialsId: 'github-read']]]) }
                dir('tools') { checkout([$class: 'GitSCM', branches: [[name: 'main']], userRemoteConfigs: [[url: 'https://github.com/Local-Narx-Space/boutique-gitops.git', credentialsId: 'github-read']]]) }
                withCredentials([string(credentialsId: 'gitops-checks', variable: 'GH_TOKEN')]) {
                    sh '''set +x
                        set -eu
                        gh api "repos/Local-Narx-Space/boutique-gitops/pulls/$PR_NUMBER" > pr.json
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
             and pr['head']['repo']['full_name'] == 'Local-Narx-Space/boutique-gitops'
             and isinstance(sha, str) and re.fullmatch(r'[a-f0-9]{40}', sha))
except (ValueError, KeyError, TypeError):
    valid = False
if not valid:
    raise SystemExit('Expected an open same-repository GitOps PR against main')
print(sha)
PR
''').trim()
                }
                dir('candidate') { checkout([$class: 'GitSCM', branches: [[name: env.PR_HEAD_SHA]], userRemoteConfigs: [[url: 'https://github.com/Local-Narx-Space/boutique-gitops.git', credentialsId: 'github-read']]]) }
            }
        }
        stage('Wait for required GitHub PR checks') {
            steps {
                withCredentials([usernamePassword(credentialsId: env.GITOPS_PR_CREDENTIAL, usernameVariable: 'GIT_USER', passwordVariable: 'GH_TOKEN')]) {
                    sh '''set +x
                        set -eu
                        python3 automation/scripts/wait-for-pr-checks.py --pr "$PR_NUMBER" --head "$PR_HEAD_SHA"
                        CURRENT_HEAD=$(gh api "repos/Local-Narx-Space/boutique-gitops/pulls/$PR_NUMBER" --jq .head.sha)
                        test "$CURRENT_HEAD" = "$PR_HEAD_SHA"
                    '''
                }
            }
        }
        stage('Queue reviewed release merge watcher') {
            when { expression { env.BOUTIQUE_RELEASE_AUTOMATION == 'true' } }
            steps { script {
                def promotion = sh(returnStdout: true, script: '''python3 - <<'PROMOTION'
import json
import re
from pathlib import Path
pr = json.loads(Path('pr.json').read_text())
print('yes' if re.fullmatch(r'jenkins/promote/(dev|staging|production)/(frontend|catalogue|cart|orders)/[1-9][0-9]*', pr['head']['ref']) else 'no')
PROMOTION
''').trim()
                if (promotion == 'yes') {
                    build job: 'Release Operations/boutique-release-verify', wait: false, parameters: [
                        string(name: 'PR_NUMBER', value: params.PR_NUMBER),
                        string(name: 'PR_HEAD_SHA', value: env.PR_HEAD_SHA)
                    ]
                } else {
                    echo 'Configuration or rollback PR: no promotion continuation queued.'
                }
            } }
        }
    }
}
