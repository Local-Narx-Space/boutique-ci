@Library('boutique-ci') _
pipeline {
    agent none
    options { timestamps(); timeout(time: 7, unit: 'DAYS'); skipDefaultCheckout(true) }
    parameters {
        string(name: 'PR_NUMBER', defaultValue: '', description: 'Validated promotion PR for any environment')
        string(name: 'PR_HEAD_SHA', defaultValue: '', description: 'Exact validated PR head')
    }
    environment {
        PR_NUMBER = "${params.PR_NUMBER}"
        PR_HEAD_SHA = "${params.PR_HEAD_SHA}"
    }
    stages {
        stage('Wait for reviewed release merge') {
            steps { script {
                if (env.BOUTIQUE_CONTROLLER_ROLE != 'release' || env.BOUTIQUE_RELEASE_AUTOMATION != 'true') { error('Enabled release controller required') }
                if (!(params.PR_NUMBER ==~ /[1-9][0-9]*/) || !(params.PR_HEAD_SHA ==~ /[a-f0-9]{40}/)) { error('Numeric PR and full validated head required') }
                // No executor is held between polls. Each API check makes only read requests with gitops-checks.
                waitUntil(initialRecurrencePeriod: 60000, quiet: true) {
                    if (env.BOUTIQUE_RELEASE_AUTOMATION != 'true') { error('Release automation disabled while waiting') }
                    def finished = false
                    node('trusted-release') {
                        deleteDir()
                        checkout([$class: 'GitSCM', branches: [[name: 'main']], userRemoteConfigs: [[url: 'https://github.com/Local-Narx-Space/boutique-ci.git', credentialsId: 'github-read']]])
                        withCredentials([string(credentialsId: 'gitops-checks', variable: 'GH_TOKEN')]) {
                            sh '''set +x
                                set -eu
                                gh api "repos/Local-Narx-Space/boutique-gitops/pulls/$PR_NUMBER" > pr.json
                            '''
                        }
                        sh 'python3 scripts/release-merge.py --pr pr.json --head "$PR_HEAD_SHA" > merge-state.json'
                        def state = sh(returnStdout: true, script: '''python3 -c "import json; print(json.load(open('merge-state.json'))['state'])"''').trim()
                        if (state == 'closed') {
                            echo 'Release PR closed without merge; no verification queued.'
                            finished = true
                        } else if (state == 'merged') {
                            env.RELEASE_COMMIT = sh(returnStdout: true, script: '''python3 -c "import json; print(json.load(open('merge-state.json'))['commit'])"''').trim()
                            env.RELEASE_TARGET = sh(returnStdout: true, script: '''python3 -c "import json; print(json.load(open('merge-state.json'))['target'])"''').trim()
                            env.RELEASE_SERVICE = sh(returnStdout: true, script: '''python3 -c "import json; print(json.load(open('merge-state.json'))['service'])"''').trim()
                            dir('gitops') {
                                checkout([$class: 'GitSCM', branches: [[name: env.RELEASE_COMMIT]], userRemoteConfigs: [[url: 'https://github.com/Local-Narx-Space/boutique-gitops.git', credentialsId: 'github-read']]])
                                // Use the exact merged selection, never a later main image.
                                env.RELEASE_IMAGE = sh(returnStdout: true, script: '''python3 - "$RELEASE_SERVICE" "$RELEASE_TARGET" <<'IMAGE'
import sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from release_config import selected_image, validate_identity
image = selected_image(Path.cwd(), sys.argv[1], sys.argv[2])
validate_identity(sys.argv[1], sys.argv[2], image)
print(image)
IMAGE
''').trim()
                            }
                            finished = true
                        }
                    }
                    return finished
                }
            } }
        }
        stage('Queue release verification') {
            when { expression { env.RELEASE_COMMIT } }
            steps {
                // The environment deployment pipeline checks main ancestry, Argo revision, image, rollout and smoke.
                build job: (env.RELEASE_TARGET == 'dev' ? 'Deployments/boutique-deploy-dev' : env.RELEASE_TARGET == 'staging' ? 'Deployments/boutique-deploy-qa' : 'Deployments/boutique-deploy-prod'), wait: false, parameters: [
                    string(name: 'ACTION', value: 'verify'),
                    string(name: 'TARGET', value: env.RELEASE_TARGET),
                    string(name: 'SERVICE', value: env.RELEASE_SERVICE),
                    string(name: 'IMAGE', value: env.RELEASE_IMAGE),
                    string(name: 'GITOPS_COMMIT', value: env.RELEASE_COMMIT)
                ]
            }
        }
    }
    post { failure { node('trusted-release') { boutiqueNotify(event: 'pipeline_failed') } } }
}
