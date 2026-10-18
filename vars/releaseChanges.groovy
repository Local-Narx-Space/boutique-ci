// Skip only known non-release paths. Unknown files always require a build.
def call(Map config) {
    def previous = currentBuild.previousBuild
    def baseline = ''
    while (previous != null) {
        def variables = previous.buildVariables
        if (previous.result == 'SUCCESS' &&
            variables.SOURCE_COMMIT ==~ /[a-f0-9]{40}/ &&
            variables.RELEASE_IMAGE ==~ /ghcr\.io\/subhankar12-spec\/boutique-[a-z-]+@sha256:[a-f0-9]{64}/ &&
            variables.RELEASE_IMAGE.startsWith("ghcr.io/subhankar12-spec/boutique-${config.service}@")) {
            baseline = variables.SOURCE_COMMIT
            break
        }
        previous = previous.previousBuild
    }
    if (!baseline) {
        echo 'No successful published release baseline retained; performing a full build.'
        return true
    }
    return withEnv(["RELEASE_BASELINE=${baseline}"]) {
        // Missing/shallow/diverged history is never evidence that a build is unnecessary.
        int historyStatus = sh(returnStatus: true, script: '''
            git cat-file -e "$RELEASE_BASELINE^{commit}" &&
            git merge-base --is-ancestor "$RELEASE_BASELINE" "$SOURCE_COMMIT"
        ''')
        if (historyStatus != 0) {
            echo 'Published release history is unavailable or divergent; performing a full build.'
            return true
        }
        // Disable rename detection so moving application code into docs still counts as a deletion.
        def paths = sh(returnStdout: true, script:
            'git diff --name-only --no-renames "$RELEASE_BASELINE" "$SOURCE_COMMIT"').readLines()
        boolean required = paths.any { path ->
            !(path.startsWith('docs/') || path.startsWith('.github/') ||
              path == 'Jenkinsfile' || path == 'LICENSE' || path == 'LICENSE.md' ||
              path == 'README' || path == 'README.md' || path == 'CONTRIBUTING.md' ||
              path == 'CODE_OF_CONDUCT.md' || path == 'CHANGELOG.md' ||
              path == '.gitignore' || path == '.editorconfig')
        }
        echo(required ? 'Release inputs changed since the last published release.' :
                        'Only documentation/CI metadata changed; skipping image build, publication and promotion.')
        return required
    }
}
