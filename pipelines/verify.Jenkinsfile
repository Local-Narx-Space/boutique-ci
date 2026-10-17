pipeline {
    agent { label 'trusted-release' }
    options { timestamps();timeout(time:20,unit:'MINUTES');disableConcurrentBuilds();skipDefaultCheckout(true) }
    parameters {
        choice(name:'TARGET',choices:['dev','staging','production'])
        choice(name:'SERVICE',choices:['frontend','catalogue','cart','orders'])
        string(name:'IMAGE',defaultValue:'',description:'Exact immutable image expected in the selected service')
        string(name:'GITOPS_COMMIT',defaultValue:'',description:'Full reviewed GitOps merge commit')
    }
    // Bind validated request parameters explicitly, including the first triggered build.
    environment {
        TARGET = "${params.TARGET}"
        SERVICE = "${params.SERVICE}"
        IMAGE = "${params.IMAGE}"
        GITOPS_COMMIT = "${params.GITOPS_COMMIT}"
    }
    stages {
        stage('Validate verification target') {
            steps { script {
                if (env.BOUTIQUE_CONTROLLER_ROLE != 'release') { error('Reviewed release controller required') }
                if (!(params.TARGET in ['dev','staging','production']) || !(params.SERVICE in ['frontend','catalogue','cart','orders'])) { error('Invalid target/service') }
                if (!(params.GITOPS_COMMIT ==~ /[a-f0-9]{40}/)) { error('Full GitOps commit required') }
                if (!(params.IMAGE ==~ /ghcr\.io\/subhankar12-spec\/boutique-[a-z-]+@sha256:[a-f0-9]{64}/) || !params.IMAGE.startsWith("ghcr.io/subhankar12-spec/boutique-${params.SERVICE}@")) { error('Expected service digest') }
                // Explicit properties avoid sandbox-blocked dynamic env indexing.
                if (params.TARGET == 'dev') {
                    env.BASE_URL = env.BOUTIQUE_DEV_ORIGIN
                } else if (params.TARGET == 'staging') {
                    env.BASE_URL = env.BOUTIQUE_STAGING_ORIGIN
                } else {
                    env.BASE_URL = env.BOUTIQUE_PRODUCTION_ORIGIN
                }
                if (!env.BASE_URL || !(env.BASE_URL.startsWith('https://') || (params.TARGET == 'dev' && env.BASE_URL == 'http://localhost:8088'))) { error('Configure HTTPS; only laptop dev may use http://localhost:8088') }
            } }
        }
        stage('Checkout protected verification tools') {
            steps {
                deleteDir()
                dir('platform') { checkout([$class:'GitSCM',branches:[[name:'main']],userRemoteConfigs:[[url:'https://github.com/subhankar12-spec/boutique-platform.git',credentialsId:'github-read']]]) }
                dir('gitops') {
                    checkout([$class:'GitSCM',branches:[[name:params.GITOPS_COMMIT]],userRemoteConfigs:[[url:'https://github.com/subhankar12-spec/boutique-gitops.git',credentialsId:'github-read']]])
                    sh 'if [ "$(git rev-parse --is-shallow-repository)" = true ]; then git fetch --unshallow origin; else git fetch origin main; fi; git merge-base --is-ancestor "$GITOPS_COMMIT" origin/main'
                }
            }
        }
        stage('Wait for Argo CD and rollout') {
            steps {
                withCredentials([file(credentialsId:"kubeconfig-${params.TARGET}",variable:'KUBECONFIG')]) {
                    sh '''set -eu
                        mkdir -p reports
                        python3 platform/scripts/wait-for-deployment.py --environment "$TARGET" --commit "$GITOPS_COMMIT" --service "$SERVICE" --image "$IMAGE" --gitops-root gitops --output reports/synchronized-commit.txt --timeout 480
                        for service in frontend catalogue cart orders; do
                            kubectl -n "boutique-$TARGET" rollout status "deployment/$service" --timeout=180s
                        done
                    '''
                }
            }
        }
        stage('Functional smoke and measured snapshots') {
            steps {
                script {
                    def smoke = {
                        sh 'python3 platform/tests/smoke/smoke.py --environment "$TARGET" --report reports/smoke.json'
                    }
                    if (env.BASE_URL.startsWith('https://')) {
                        if (env.BOUTIQUE_USE_PRIVATE_CA == 'true') {
                            withCredentials([file(credentialsId: "boutique-ca-${params.TARGET}", variable: 'SSL_CERT_FILE')]) { smoke() }
                        } else { smoke() } // Publicly trusted Cloudflare/AWS certificates use system CAs.
                    } else { smoke() }
                }
                withCredentials([file(credentialsId: "kubeconfig-${params.TARGET}", variable: 'KUBECONFIG')]) {
                    sh '''set -eu
                        kubectl -n "boutique-$TARGET" get deployments -o json > reports/deployments.json
                        kubectl -n argocd get application "boutique-$TARGET" -o json > reports/argocd.json
                    '''
                }
            }
        }
        stage('Promote verified dev release to staging') {
            when { expression { env.BOUTIQUE_RELEASE_AUTOMATION == 'true' && params.TARGET == 'dev' } }
            steps {
                // IMAGE pins the verified dev digest; promotion fails if dev has moved on.
                build job: 'boutique-promote', wait: false, parameters: [
                    string(name: 'TARGET', value: 'staging'),
                    string(name: 'SERVICE', value: params.SERVICE),
                    string(name: 'IMAGE', value: params.IMAGE),
                    string(name: 'RELEASE_BUILD', value: '')
                ]
            }
        }
    }
    post { always { archiveArtifacts artifacts: 'reports/*', allowEmptyArchive: true, fingerprint: true } }
}
