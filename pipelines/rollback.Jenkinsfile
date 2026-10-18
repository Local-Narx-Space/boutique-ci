@Library('boutique-ci') _
pipeline {
    agent { label 'trusted-release' }
    options { timestamps(); timeout(time: 20, unit: 'MINUTES'); disableConcurrentBuilds(); skipDefaultCheckout(true) }
    parameters {
        choice(name: 'TARGET', choices: ['dev','staging','production'])
        choice(name: 'SERVICE', choices: ['frontend','catalogue','cart','orders'])
        string(name: 'GITOPS_COMMIT', defaultValue: '', description: 'Previous protected-main commit containing the known-good service image/chart')
    }
    // Bind validated request parameters explicitly, including the first triggered build.
    environment {
        TARGET = "${params.TARGET}"
        SERVICE = "${params.SERVICE}"
        GITOPS_COMMIT = "${params.GITOPS_COMMIT}"
    }
    stages {
        stage('Validate recovery request') {
            steps { script {
                if (env.BOUTIQUE_CONTROLLER_ROLE != 'release' || !(params.GITOPS_COMMIT ==~ /[a-f0-9]{40}/)) { error('Release controller and full GitOps commit required') }
                if (!(params.TARGET in ['dev','staging','production']) || !(params.SERVICE in ['frontend','catalogue','cart','orders'])) { error('Invalid target/service') }
            } }
        }
        stage('Checkout GitOps history') {
            steps {
                deleteDir()
                checkout([$class: 'GitSCM', branches: [[name: 'main']], userRemoteConfigs: [[url: 'https://github.com/Local-Narx-Space/boutique-gitops.git', credentialsId: 'github-read']]])
                sh 'if [ "$(git rev-parse --is-shallow-repository)" = true ]; then git fetch --unshallow origin; else git fetch origin main; fi'
            }
        }
        stage('Restore previous image and chart selection') {
            steps {
                sh 'python3 scripts/rollback.py "$SERVICE" "$TARGET" "$GITOPS_COMMIT"'
                // boutique-gitops-validate checks the exact rollback PR head.
                sh 'git diff -- environments > planned-change.diff'
            }
        }
        stage('Open recovery PR') { steps { gitopsPullRequest(action: 'rollback') } }
    }
}
