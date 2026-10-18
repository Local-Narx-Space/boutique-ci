def call(Map config) {
    def allowed = ['frontend', 'catalogue', 'cart', 'orders']
    if (!(config.service in allowed)) { error('Unsupported service') }
    def isRelease = { env.BOUTIQUE_CONTROLLER_ROLE == 'release' && env.BRANCH_NAME == 'main' && !env.CHANGE_ID }
    pipeline {
        agent none
        options {
            timestamps()
            timeout(time: 60, unit: 'MINUTES')
            buildDiscarder(logRotator(numToKeepStr: '40', artifactNumToKeepStr: '30'))
            disableConcurrentBuilds()
            skipStagesAfterUnstable()
            skipDefaultCheckout(true)
            copyArtifactPermission('boutique-deploy-dev')
        }
        parameters { booleanParam(name: 'DELIVER_TO_DEV', defaultValue: true, description: 'Open a reviewed dev GitOps PR after publication') }
        environment {
            SERVICE = "${config.service}"
            REGISTRY = 'ghcr.io'
            GITHUB_OWNER = 'subhankar12-spec'
        }
        stages {
            stage('Validate, build and publish') {
                agent { label "${env.BOUTIQUE_CONTROLLER_ROLE == 'release' ? 'trusted-release' : 'isolated-builder'}" }
                stages {
                    stage('Checkout') {
                        steps {
                            deleteDir(); checkout scm
                            script {
                                if (env.BOUTIQUE_CONTROLLER_ROLE == 'release' && !isRelease()) {
                                    error('Release controller accepts protected main branch builds only')
                                }
                                env.SOURCE_COMMIT = sh(script: 'git rev-parse HEAD', returnStdout: true).trim()
                                env.IMAGE_TAG = "${env.REGISTRY}/${env.GITHUB_OWNER}/boutique-${config.service}:${env.SOURCE_COMMIT}"
                                env.TEST_IMAGE = "${env.IMAGE_TAG}-test"
                                // A numeric agent UID may inherit HOME=/; keep tool state private and writable.
                                env.HOME = "${pwd(tmp: true)}/home"
                                env.XDG_CACHE_HOME = "${env.HOME}/.cache"
                                env.TRIVY_CACHE_DIR = "${env.XDG_CACHE_HOME}/trivy"
                                env.DOCKER_CONFIG = "${pwd()}/.docker"
                                sh 'install -d -m 700 "$HOME" "$XDG_CACHE_HOME" "$TRIVY_CACHE_DIR" "$DOCKER_CONFIG"'
                                // Non-release validation continues normally. Release skips use the last
                                // successful publication, not the last build (which may itself be skipped).
                                env.RELEASE_BUILD_REQUIRED = (!isRelease() || releaseChanges(service: config.service)).toString()
                                if (env.RELEASE_BUILD_REQUIRED == 'false') {
                                    currentBuild.description = 'No release changes: build/publication/promotion skipped'
                                }
                            }
                        }
                    }
                    stage('Validate protected source') {
                        when { expression { isRelease() } }
                        steps { sh 'git fetch origin main && git merge-base --is-ancestor "$SOURCE_COMMIT" origin/main' }
                    }
                    stage('Source secret scan') {
                        // Secret detection needs source files, not remote Maven dependency resolution.
                        steps { sh 'trivy fs --scanners secret --offline-scan --skip-version-check --exit-code 1 --severity HIGH,CRITICAL .' }
                    }
                    stage('Release work') {
                        when { expression { env.RELEASE_BUILD_REQUIRED == 'true' } }
                        stages {
                            stage('AWS trust bundle') {
                                when { expression { isRelease() && config.service == 'orders' } }
                                steps { sh 'cd certs && sha256sum -c global-bundle.sha256 && openssl crl2pkcs7 -nocrl -certfile global-bundle.pem | openssl pkcs7 -print_certs -noout >/dev/null' }
                            }
                            stage('Helm validation and packaging') {
                                steps {
                                    sh '''set -eu
                                        helm lint --strict helm
                                        helm template "boutique-$SERVICE" helm --namespace boutique-dev > chart-render.yaml
                                        kubeconform -strict -summary -kubernetes-version 1.34.0 chart-render.yaml
                                        mkdir -p chart-package
                                        helm package helm --version "0.1.0-$SOURCE_COMMIT" --app-version "$SOURCE_COMMIT" --destination chart-package
                                        cp "chart-package/boutique-$SERVICE-0.1.0-$SOURCE_COMMIT.tgz" chart.tgz
                                    '''
                                }
                            }
                            stage('Build and test') {
                                parallel {
                                    stage('Test') {
                                        steps {
                                            sh '''set -eu
                                                mkdir -p test-reports
                                                docker build --pull --target test --tag "$TEST_IMAGE" .
                                                test_user="$(id -u):$(id -g)"
                                                docker_security=$(docker info --format '{{json .SecurityOptions}}')
                                                # Rootless container UID 0 maps to the unprivileged daemon owner.
                                                # Reusing the host UID would map to a subordinate UID instead.
                                                case "$docker_security" in
                                                    *'"name=rootless"'*) test_user=0:0 ;;
                                                esac
                                                docker run --rm --user "$test_user" --env HOME=/tmp \
                                                    --cap-drop ALL --security-opt no-new-privileges:true \
                                                    --mount "type=bind,source=$WORKSPACE/test-reports,target=/reports" "$TEST_IMAGE"
                                            '''
                                        }
                                        post {
                                            always {
                                                script {
                                                    try {
                                                        junit testResults: 'test-reports/**/*.xml', allowEmptyResults: false, skipPublishingChecks: true
                                                    } finally {
                                                        archiveArtifacts artifacts: 'test-reports/**', allowEmptyArchive: true
                                                        sh 'docker image rm "$TEST_IMAGE" >/dev/null 2>&1 || true'
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    stage('Build image') {
                                        steps {
                                            sh '''
                                        set -eu
                                        export DOCKER_CONFIG="$WORKSPACE/.docker"
                                        mkdir -p "$DOCKER_CONFIG"
                                        docker build --pull --tag "$IMAGE_TAG" .
                                        printf '%s\n' "$IMAGE_TAG" > image.txt
                                    '''
                                        }
                                    }
                                }
                            }
                            stage('Security and SBOM') {
                                parallel {
                                    stage('Image security scan') {
                                        steps {
                                            sh 'trivy image --format json --output image-scan.json --ignorefile .trivyignore.yaml --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed "$IMAGE_TAG"'
                                        }
                                    }
                                    stage('Generate SBOM') {
                                        steps { sh 'syft "$IMAGE_TAG" -o cyclonedx-json=sbom.json' }
                                    }
                                }
                            }
                            stage('Publish tested artifact') {
                                when { expression { isRelease() } }
                                steps {
                                    withCredentials([usernamePassword(credentialsId: 'ghcr-publish', usernameVariable: 'REGISTRY_USER', passwordVariable: 'REGISTRY_TOKEN')]) {
                                        sh '''set +x
                                    set -eu
                                    export DOCKER_CONFIG="$WORKSPACE/.docker"
                                    export HELM_REGISTRY_CONFIG="$DOCKER_CONFIG/helm-registry.json"
                                    trap 'docker logout "$REGISTRY" >/dev/null 2>&1 || true; helm registry logout "$REGISTRY" >/dev/null 2>&1 || true' EXIT
                                    printf '%s' "$REGISTRY_TOKEN" | docker login "$REGISTRY" -u "$REGISTRY_USER" --password-stdin
                                    if docker manifest inspect "$IMAGE_TAG" >/dev/null 2> registry-check.log; then
                                        echo 'Commit tag already exists; refusing to overwrite it. Promote its recorded release instead.'
                                        exit 1
                                    fi
                                    if ! grep -Eqi 'manifest unknown|no such manifest|NAME_UNKNOWN|MANIFEST_UNKNOWN' registry-check.log; then
                                        echo 'Cannot establish registry tag availability; refusing publication.'
                                        exit 1
                                    fi
                                    printf '%s' "$REGISTRY_TOKEN" | helm registry login "$REGISTRY" -u "$REGISTRY_USER" --password-stdin
                                    if helm show chart "oci://$REGISTRY/$GITHUB_OWNER/charts/boutique-$SERVICE" --version "0.1.0-$SOURCE_COMMIT" >/dev/null 2> chart-registry-check.log; then
                                        echo 'Chart version already exists; refusing to overwrite it.'; exit 1
                                    fi
                                    if ! grep -Eqi 'manifest unknown|not found|NAME_UNKNOWN|MANIFEST_UNKNOWN|404' chart-registry-check.log; then
                                        echo 'Cannot establish chart version availability; refusing publication.'; exit 1
                                    fi
                                    docker push "$IMAGE_TAG"
                                    docker inspect --format '{{index .RepoDigests 0}}' "$IMAGE_TAG" > image-digest.txt
                                    helm push "chart-package/boutique-$SERVICE-0.1.0-$SOURCE_COMMIT.tgz" "oci://$REGISTRY/$GITHUB_OWNER/charts" > chart-push.log 2>&1
                                '''
                                    }
                                    script {
                                        env.RELEASE_IMAGE = readFile('image-digest.txt').trim()
                                        if (!(env.RELEASE_IMAGE ==~ /ghcr\.io\/subhankar12-spec\/boutique-[a-z-]+@sha256:[a-f0-9]{64}/)) { error('Missing immutable registry digest') }
                                    }
                                    sh 'printf "%s\\n" "$SOURCE_COMMIT" > source-commit.txt'
                        }
                    }
                        }
                    }

                }
                post {
                    always {
                        archiveArtifacts artifacts: 'image.txt,image-digest.txt,source-commit.txt,sbom.json,image-scan.json,chart.tgz,chart-render.yaml', allowEmptyArchive: true, fingerprint: true
                        sh 'rm -rf .docker'
                    }
                }
            }
            stage('Deliver to dev') {
                when { expression { isRelease() && env.RELEASE_BUILD_REQUIRED == 'true' && params.DELIVER_TO_DEV } }
                steps {
                    // Queue delivery and finish the source build. Promotion and
                    // deployment status are tracked by their own downstream jobs.
                    build job: 'boutique-deploy-dev', wait: false, parameters: [
                        string(name: 'ACTION', value: 'promote'),
                        string(name: 'TARGET', value: 'dev'),
                        string(name: 'SERVICE', value: config.service),
                        string(name: 'IMAGE', value: env.RELEASE_IMAGE),
                        string(name: 'RELEASE_BUILD', value: env.BUILD_NUMBER)
                    ]
                }
            }
        }

    }
}
