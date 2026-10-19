def call() {
    if (!(params.SERVICE in ['frontend','catalogue','cart','orders']) || !(params.RELEASE_BUILD ==~ /[1-9][0-9]*/)) {
        error('Select a service and its protected-main publishing build number')
    }
    dir('release-artifacts') { deleteDir() }
    copyArtifacts projectName: "/Services/boutique-${params.SERVICE}/main", selector: specific(params.RELEASE_BUILD),
        filter: 'image-digest.txt,source-commit.txt,chart.tgz', target: 'release-artifacts', flatten: true
    def image = readFile('release-artifacts/image-digest.txt').trim()
    def source = readFile('release-artifacts/source-commit.txt').trim()
    if (!(source ==~ /[a-f0-9]{40}/) || image != params.IMAGE || !image.startsWith("ghcr.io/subhankar12-spec/boutique-${params.SERVICE}@sha256:")) {
        error('Publishing artifacts differ from the requested release')
    }
    withEnv(["RELEASE_SOURCE_COMMIT=${source}", "SERVICE=${params.SERVICE}", "IMAGE=${image}"]) {
        sh 'python3 scripts/promote.py "$SERVICE" dev "$IMAGE" --chart-package release-artifacts/chart.tgz --source-commit "$RELEASE_SOURCE_COMMIT"'
    }
}
