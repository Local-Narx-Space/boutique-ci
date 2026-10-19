def call(Map config) {
pipeline {
    agent { label 'trusted-release' }
    options { timestamps();timeout(time:20,unit:'MINUTES');disableConcurrentBuilds();skipDefaultCheckout(true) }
    parameters {
        choice(name:'ACTION', choices:['promote','verify'], description:'Request a release PR or verify the merged release')
        choice(name:'TARGET', choices:[config.target])
        choice(name:'SERVICE', choices:['frontend','catalogue','cart','orders'])
        string(name:'IMAGE', defaultValue:'', description:'Immutable service image digest')
        string(name:'RELEASE_BUILD', defaultValue:'', description:'Dev publishing build number')
        string(name:'GITOPS_COMMIT', defaultValue:'', description:'Merged GitOps commit for verification')
    }
    // Bind validated request parameters explicitly, including the first triggered build.
    environment {
        TARGET = "${params.TARGET}"
        SERVICE = "${params.SERVICE}"
        IMAGE = "${params.IMAGE}"
        GITOPS_COMMIT = "${params.GITOPS_COMMIT}"
        RELEASE_BUILD = "${params.RELEASE_BUILD}"
    }
    stages {
        stage('Validate request') {
            steps { script {
                if (env.BOUTIQUE_CONTROLLER_ROLE != 'release') { error('Reviewed release controller required') }
                if (params.TARGET != config.target) { error('This pipeline is restricted to its configured environment') }
                if (!(params.ACTION in ['promote','verify'])) { error('Invalid deployment action') }
                currentBuild.displayName = "#${env.BUILD_NUMBER} ${params.ACTION} ${params.SERVICE}"
                if (params.ACTION == 'promote') {
                if (!(params.TARGET in ['dev','staging','production']) || !(params.SERVICE in ['frontend','catalogue','cart','orders'])) { error('Invalid target/service') }
                if (params.IMAGE && !(params.IMAGE ==~ /ghcr\.io\/subhankar12-spec\/boutique-[a-z-]+@sha256:[a-f0-9]{64}/)) { error('Expected immutable image digest') }
                if (params.TARGET == 'dev' && !params.IMAGE) { error('Dev requires the publishing build image digest') }
                } else {
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
                }
                if (params.ACTION == 'verify') { boutiqueNotify(event: 'deployment_started', service: params.SERVICE, target: params.TARGET) }
            } }
        }
        stage('Checkout release tools') {
            steps { script {
                deleteDir()
                if (params.ACTION == 'promote') {
                    checkout([$class:'GitSCM',branches:[[name:'main']],userRemoteConfigs:[[url:'https://github.com/Local-Narx-Space/boutique-gitops.git',credentialsId:'github-read']]])
                } else {
                    dir('platform') { checkout([$class:'GitSCM',branches:[[name:'main']],userRemoteConfigs:[[url:'https://github.com/Local-Narx-Space/boutique-platform.git',credentialsId:'github-read']]]) }
                    dir('gitops') {
                        checkout([$class:'GitSCM',branches:[[name:params.GITOPS_COMMIT]],userRemoteConfigs:[[url:'https://github.com/Local-Narx-Space/boutique-gitops.git',credentialsId:'github-read']]])
                        sh 'if [ "$(git rev-parse --is-shallow-repository)" = true ]; then git fetch --unshallow origin; else git fetch origin main; fi; git merge-base --is-ancestor "$GITOPS_COMMIT" origin/main'
                    }
                }
            } }
        }
        stage('Select immutable release') {
            when { expression { params.ACTION == 'promote' } }
            steps { script {
                if (params.TARGET == 'dev') { releaseArtifact() }
                else { sh 'python3 scripts/promote.py "$SERVICE" "$TARGET" ${IMAGE:+"$IMAGE"}' }
            } }
        }
        stage('Open deployment PR') {
            when { expression { params.ACTION == 'promote' } }
            steps { script {
                sh 'git diff -- environments > planned-change.diff'
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
        stage('Wait for Argo CD and rollout') {
            when { expression { params.ACTION == 'verify' } }
            steps {
                withCredentials([file(credentialsId:"kubeconfig-${params.TARGET}",variable:'KUBECONFIG')]) {
                    sh '''set -eu
                        mkdir -p reports
                        python3 platform/scripts/wait-for-deployment.py --environment "$TARGET" --commit "$GITOPS_COMMIT" --service "$SERVICE" --image "$IMAGE" --gitops-root gitops --output reports/synchronized-commit.txt --workloads-output reports/workloads.json --timeout 900
                        for service in frontend catalogue cart orders; do
                            if [ "$(python3 -c 'import json,sys; print(json.load(open("reports/workloads.json"))[sys.argv[1]])' "$service")" = Rollout ]; then
                                # Protected verifier measured the active Service and stable ReplicaSet.
                                kubectl -n "boutique-$TARGET" get rollout.argoproj.io "$service" -o json > "reports/$service-rollout.json"
                            else
                                kubectl -n "boutique-$TARGET" rollout status "deployment/$service" --timeout=180s
                            fi
                        done
                    '''
                }
            }
        }
        stage('Functional smoke and measured snapshots') {
            when { expression { params.ACTION == 'verify' } }
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
            when { expression { params.ACTION == 'verify' && env.BOUTIQUE_RELEASE_AUTOMATION == 'true' && params.TARGET == 'dev' } }
            steps {
                // IMAGE pins the verified dev digest; promotion fails if dev has moved on.
                build job: 'Deployments/boutique-deploy-qa', wait: false, parameters: [
                    string(name: 'ACTION', value: 'promote'),
                    string(name: 'TARGET', value: 'staging'),
                    string(name: 'SERVICE', value: params.SERVICE),
                    string(name: 'IMAGE', value: params.IMAGE),
                    string(name: 'RELEASE_BUILD', value: '')
                ]
            }
        }
        stage('Open human-reviewed production promotion') {
            when { expression { params.ACTION == 'verify' && env.BOUTIQUE_RELEASE_AUTOMATION == 'true' && params.TARGET == 'staging' } }
            steps {
                // Only a fully deployed and smoke-verified staging digest can
                // reach this stage. The promotion job opens a production PR;
                // production still requires a human merge.
                build job: 'Deployments/boutique-deploy-prod', wait: false, parameters: [
                    string(name: 'ACTION', value: 'promote'),
                    string(name: 'TARGET', value: 'production'),
                    string(name: 'SERVICE', value: params.SERVICE),
                    string(name: 'IMAGE', value: params.IMAGE),
                    string(name: 'RELEASE_BUILD', value: '')
                ]
            }
        }
    }
    post {
        success { script {
            if (params.ACTION == 'verify') { boutiqueNotify(event: 'deployment_passed', service: params.SERVICE, target: params.TARGET) }
        } }
        failure { script {
            // Capture actual recovery evidence; never label every failed build a rollback.
            def recovered = false
            if (params.ACTION == 'verify' && params.TARGET in ['staging','production'] &&
                params.SERVICE in ['frontend','catalogue','cart','orders']) {
                try {
                    withCredentials([file(credentialsId: "kubeconfig-${params.TARGET}", variable: 'KUBECONFIG')]) {
                        sh(returnStatus: true, script: '''set +x
                            mkdir -p reports
                            kubectl -n "boutique-$TARGET" get rollout.argoproj.io "$SERVICE" -o json > reports/failed-rollout.json
                            kubectl -n "boutique-$TARGET" get service "$SERVICE" -o json > reports/recovered-service.json
                        ''')
                    }
                    recovered = sh(returnStatus: true, script: '''python3 - <<'RECOVERY'
import json
r = json.load(open('reports/failed-rollout.json')).get('status', {})
s = json.load(open('reports/recovered-service.json'))
assert r.get('abort') is True
assert r.get('stableRS') and s['spec']['selector']['rollouts-pod-template-hash'] == r['stableRS']
RECOVERY
''') == 0
                } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException interrupted) { throw interrupted
                } catch (Exception ignored) { echo 'Recovery evidence unavailable; reporting verification failure.' }
            }
            boutiqueNotify(event: recovered ? 'rollback_recovered' : 'deployment_failed', service: params.SERVICE, target: params.TARGET)
        } }
        cleanup { archiveArtifacts artifacts:'reports/*', allowEmptyArchive:true, fingerprint:true }
    }
}
}
