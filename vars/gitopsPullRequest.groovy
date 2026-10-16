def call(Map config) {
    def action = config.action
    if (!(action in ['promote','rollback']) || !(params.SERVICE in ['frontend','catalogue','cart','orders']) || !(params.TARGET in ['dev','staging','production'])) {
        error('Invalid GitOps request')
    }
    writeFile file: 'gitops-pr-body.md', text: """${action.capitalize()} ${params.SERVICE} in ${params.TARGET}.

Jenkins build: ${env.BUILD_URL}
Publishing build: ${params.RELEASE_BUILD ?: 'Existing GitOps release'}
Rollback commit: ${params.GITOPS_COMMIT ?: 'Not applicable'}

Review the image digest, chart package, validation result and database migration compatibility.
For promotion, confirm the preceding environment's rollout and smoke tests passed.
Argo CD deploys after this PR is reviewed and merged. This job does not merge it.
"""
    withCredentials([usernamePassword(credentialsId: 'gitops-pr', usernameVariable: 'GIT_USER', passwordVariable: 'GH_TOKEN')]) {
        withEnv(["GITOPS_ACTION=${action}", "SERVICE=${params.SERVICE}", "TARGET=${params.TARGET}"]) {
            sh '''set +x
                set -eu
                BRANCH="jenkins/$GITOPS_ACTION/$TARGET/$SERVICE/$BUILD_NUMBER"
                git config user.name boutique-jenkins
                git config user.email boutique-jenkins@users.noreply.github.com
                git checkout -b "$BRANCH"
                git add environments
                if git diff --cached --quiet; then
                    echo 'No deployment change to propose'; exit 1
                fi
                git commit -m "$GITOPS_ACTION $SERVICE in $TARGET"
                ASKPASS=$(mktemp)
                trap 'rm -f "$ASKPASS"' EXIT
                printf '#!/bin/sh\ncase "$1" in *Username*) printf "%%s" "$GIT_USER";; *) printf "%%s" "$GH_TOKEN";; esac\n' > "$ASKPASS"
                chmod 700 "$ASKPASS"
                GIT_ASKPASS="$ASKPASS" GIT_TERMINAL_PROMPT=0 git push origin "$BRANCH"
                gh pr create --repo subhankar12-spec/boutique-gitops --base main --head "$BRANCH" --title "$GITOPS_ACTION $SERVICE in $TARGET" --body-file gitops-pr-body.md > gitops-pr-url.txt
            '''
        }
    }
    withCredentials([usernamePassword(credentialsId: 'gitops-pr', usernameVariable: 'GIT_USER', passwordVariable: 'GH_TOKEN')]) {
        sh 'set +x; gh pr view --repo subhankar12-spec/boutique-gitops "$(cat gitops-pr-url.txt)" --json number --jq .number > gitops-pr-number.txt'
    }
    def number = readFile('gitops-pr-number.txt').trim()
    if (!(number ==~ /[1-9][0-9]*/)) { error('Missing GitOps PR number') }
    // Queue without waiting: one shared executor runs validation after this job ends.
    build job: 'boutique-gitops-validate', wait: false, parameters: [string(name: 'PR_NUMBER', value: number)]
    archiveArtifacts artifacts: 'gitops-pr-url.txt,planned-change.diff', fingerprint: true
    echo "Review and merge the PR: ${readFile('gitops-pr-url.txt').trim()}"
}
