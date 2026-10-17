pipeline {
    agent none
    options { timestamps(); timeout(time: 7, unit: 'DAYS'); skipDefaultCheckout(true) }
    parameters {
        string(name: 'PR_NUMBER', defaultValue: '', description: 'Validated production promotion PR')
        string(name: 'PR_HEAD_SHA', defaultValue: '', description: 'Exact validated PR head')
    }
    environment {
        PR_NUMBER = "${params.PR_NUMBER}"
        PR_HEAD_SHA = "${params.PR_HEAD_SHA}"
    }
    stages {
        stage('Wait for human-reviewed production merge') {
            steps { script {
                if (env.BOUTIQUE_CONTROLLER_ROLE != 'release' || env.BOUTIQUE_RELEASE_AUTOMATION != 'true') { error('Enabled release controller required') }
                if (!(params.PR_NUMBER ==~ /[1-9][0-9]*/) || !(params.PR_HEAD_SHA ==~ /[a-f0-9]{40}/)) { error('Numeric PR and full validated head required') }
                // No executor is held between polls. Each API check makes only read requests with gitops-checks.
                waitUntil(initialRecurrencePeriod: 60000, quiet: true) {
                    if (env.BOUTIQUE_RELEASE_AUTOMATION != 'true') { error('Release automation disabled while waiting') }
                    def finished = false
                    node('trusted-release') {
                        deleteDir()
                        checkout([$class: 'GitSCM', branches: [[name: 'main']], userRemoteConfigs: [[url: 'https://github.com/subhankar12-spec/boutique-ci.git', credentialsId: 'github-read']]])
                        withCredentials([string(credentialsId: 'gitops-checks', variable: 'GH_TOKEN')]) {
                            sh '''set +x
                                set -eu
                                gh api "repos/subhankar12-spec/boutique-gitops/pulls/$PR_NUMBER" > pr.json
                            '''
                        }
                        sh 'python3 scripts/production-merge.py --pr pr.json --head "$PR_HEAD_SHA" > merge-state.json'
                        def state = sh(returnStdout: true, script: '''python3 -c "import json; print(json.load(open('merge-state.json'))['state'])"''').trim()
                        if (state == 'closed') {
                            echo 'Production PR closed without merge; no verification queued.'
                            finished = true
                        } else if (state == 'merged') {
                            env.PRODUCTION_COMMIT = sh(returnStdout: true, script: '''python3 -c "import json; print(json.load(open('merge-state.json'))['commit'])"''').trim()
                            env.PRODUCTION_SERVICE = sh(returnStdout: true, script: '''python3 -c "import json; print(json.load(open('merge-state.json'))['service'])"''').trim()
                            dir('gitops') {
                                checkout([$class: 'GitSCM', branches: [[name: env.PRODUCTION_COMMIT]], userRemoteConfigs: [[url: 'https://github.com/subhankar12-spec/boutique-gitops.git', credentialsId: 'github-read']]])
                                // Use the exact merged selection, never a later main image.
                                env.PRODUCTION_IMAGE = sh(returnStdout: true, script: '''python3 - "$PRODUCTION_SERVICE" <<'IMAGE'
import sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from release_config import selected_image, validate_identity
image = selected_image(Path.cwd(), sys.argv[1], 'production')
validate_identity(sys.argv[1], 'production', image)
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
        stage('Queue production verification') {
            when { expression { env.PRODUCTION_COMMIT } }
            steps {
                // The production deployment pipeline checks main ancestry, Argo revision, image, rollout and smoke.
                build job: 'boutique-deploy-prod', wait: false, parameters: [
                    string(name: 'ACTION', value: 'verify'),
                    string(name: 'TARGET', value: 'production'),
                    string(name: 'SERVICE', value: env.PRODUCTION_SERVICE),
                    string(name: 'IMAGE', value: env.PRODUCTION_IMAGE),
                    string(name: 'GITOPS_COMMIT', value: env.PRODUCTION_COMMIT)
                ]
            }
        }
    }
}
