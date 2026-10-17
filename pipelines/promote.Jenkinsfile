@Library('boutique-ci') _
pipeline {
    agent { label 'trusted-release' }
    options { timestamps(); timeout(time: 20, unit: 'MINUTES'); disableConcurrentBuilds(); skipDefaultCheckout(true) }
    parameters {
        choice(name: 'TARGET', choices: ['dev','staging','production'])
        choice(name: 'SERVICE', choices: ['frontend','catalogue','cart','orders'])
        string(name: 'IMAGE', defaultValue: '', description: 'Dev: published service digest. Other environments copy the preceding selection.')
        string(name: 'RELEASE_BUILD', defaultValue: '', description: 'Dev only: service/main publishing build number')
    }
    // Bind validated request parameters explicitly, including the first triggered build.
    environment {
        TARGET = "${params.TARGET}"
        SERVICE = "${params.SERVICE}"
        IMAGE = "${params.IMAGE}"
        RELEASE_BUILD = "${params.RELEASE_BUILD}"
    }
    stages {
        stage('Validate request') {
            steps { script {
                if (env.BOUTIQUE_CONTROLLER_ROLE != 'release') { error('Reviewed release controller required') }
                if (!(params.TARGET in ['dev','staging','production']) || !(params.SERVICE in ['frontend','catalogue','cart','orders'])) { error('Invalid target/service') }
                if (params.IMAGE && !(params.IMAGE ==~ /ghcr\.io\/subhankar12-spec\/boutique-[a-z-]+@sha256:[a-f0-9]{64}/)) { error('Expected immutable image digest') }
                if (params.TARGET == 'dev' && !params.IMAGE) { error('Dev requires the publishing build image digest') }
            } }
        }
        stage('Checkout GitOps') {
            steps {
                deleteDir()
                checkout([$class: 'GitSCM', branches: [[name: 'main']], userRemoteConfigs: [[url: 'https://github.com/subhankar12-spec/boutique-gitops.git', credentialsId: 'github-read']]])
            }
        }
        stage('Select immutable release') {
            steps { script {
                if (params.TARGET == 'dev') { releaseArtifact() }
                else { sh 'python3 scripts/promote.py "$SERVICE" "$TARGET" ${IMAGE:+"$IMAGE"}' }
            } }
        }
        stage('Record planned change') {
            steps {
                // The required PR validator checks the exact candidate once.
                sh 'git diff -- environments > planned-change.diff'
            }
        }
        stage('Open deployment PR') {
            steps { script {
                int changeStatus = sh(returnStatus: true, script: 'git diff --quiet -- environments')
                if (changeStatus == 0) {
                    echo 'Selected release is already deployed; no deployment PR is needed'
                } else if (changeStatus == 1) {
                    gitopsPullRequest(action: 'promote')
                } else {
                    error('Unable to determine the deployment change')
                }
            } }
        }
    }
}
