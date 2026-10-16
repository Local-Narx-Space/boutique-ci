pipeline {
    agent { label 'trusted-release' }
    options { timestamps(); timeout(time: 20, unit: 'MINUTES'); disableConcurrentBuilds(); skipDefaultCheckout(true) }
    parameters { string(name: 'PR_NUMBER', defaultValue: '', description: 'GitOps PR number to validate') }
    // Bind validated request parameters explicitly, including the first triggered build.
    environment {
        PR_NUMBER = "${params.PR_NUMBER}"
    }
    stages {
        stage('Validate request') {
            steps { script {
                if (env.BOUTIQUE_CONTROLLER_ROLE != 'release' || !(params.PR_NUMBER ==~ /[1-9][0-9]*/)) { error('Reviewed controller and numeric PR required') }
            } }
        }
        stage('Fetch protected tools and PR revision') {
            steps {
                deleteDir()
                dir('tools') { checkout([$class: 'GitSCM', branches: [[name: 'main']], userRemoteConfigs: [[url: 'https://github.com/subhankar12-spec/boutique-gitops.git', credentialsId: 'github-read']]]) }
                withCredentials([string(credentialsId: 'gitops-checks', variable: 'GH_TOKEN')]) {
                    sh '''set +x
                        set -eu
                        gh api "repos/subhankar12-spec/boutique-gitops/pulls/$PR_NUMBER" > pr.json
                    '''
                }
                script {
                    def pr = new groovy.json.JsonSlurperClassic().parseText(readFile('pr.json'))
                    if (pr.state != 'open' || pr.base.ref != 'main' || pr.head.repo.full_name != 'subhankar12-spec/boutique-gitops' || !(pr.head.sha ==~ /[a-f0-9]{40}/)) { error('Expected an open same-repository GitOps PR against main') }
                    env.PR_HEAD_SHA = pr.head.sha
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
                sh 'bash tools/scripts/validate.sh "$WORKSPACE/candidate"'
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
