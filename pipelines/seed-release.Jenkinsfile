// Configure the seed as Pipeline from SCM, pinned to a reviewed boutique-ci commit.
pipeline {
    agent { label 'trusted-release' }
    options {
        disableConcurrentBuilds()
        skipDefaultCheckout(true)
        timeout(time: 10, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }
    parameters {
        booleanParam(name: 'SUPPRESS_AUTOMATIC_BUILDS', defaultValue: true,
            description: 'Keep service builds manual during bootstrap; disable after delivery is configured.')
    }
    stages {
        stage('Check controller role') {
            steps {
                script {
                    if (env.BOUTIQUE_CONTROLLER_ROLE != 'release') {
                        error('Run this reviewed seed only on the release controller')
                    }
                }
            }
        }
        stage('Checkout reviewed job definitions') {
            steps { deleteDir(); checkout scm }
        }
        stage('Create release jobs') {
            steps {
                jobDsl targets: 'jenkins/jobs/release.groovy',
                    sandbox: true,
                    failOnMissingPlugin: true,
                    removedJobAction: 'IGNORE',
                    removedViewAction: 'IGNORE',
                    additionalParameters: [suppressAutomaticBuilds: params.SUPPRESS_AUTOMATIC_BUILDS]
            }
        }
    }
}
