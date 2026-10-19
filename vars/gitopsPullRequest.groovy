def call(Map config) {
    def action = config.action
    def credentialId = env.BOUTIQUE_GITOPS_PR_CREDENTIAL ?: 'gitops-pr'
    if (!(action in ['promote','rollback']) || !(params.SERVICE in ['frontend','catalogue','cart','orders']) || !(params.TARGET in ['dev','staging','production'])) {
        error('Invalid GitOps request')
    }
    writeFile file: 'gitops-pr-body.md', text: """${action.capitalize()} ${params.SERVICE} in ${params.TARGET}.

Jenkins build: ${env.BUILD_URL}
Publishing build: ${params.RELEASE_BUILD ?: 'Existing GitOps release'}
Rollback commit: ${params.GITOPS_COMMIT ?: 'Not applicable'}

Review the image digest, chart package, validation result and database migration compatibility.
For promotion, confirm the preceding environment's rollout and smoke tests passed.
Generated dev/QA image-and-chart promotions merge automatically after required checks. Production, rollback and configuration changes require code-owner review. A shared watcher verifies every merged promotion. Argo CD deploys merged changes.
"""
    withCredentials([usernamePassword(credentialsId: credentialId, usernameVariable: 'GIT_USER', passwordVariable: 'GH_TOKEN')]) {
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
                gh pr create --repo Local-Narx-Space/boutique-gitops --base main --head "$BRANCH" --title "$GITOPS_ACTION $SERVICE in $TARGET" --body-file gitops-pr-body.md > gitops-pr-url.txt
            '''
        }
    }
    withCredentials([usernamePassword(credentialsId: credentialId, usernameVariable: 'GIT_USER', passwordVariable: 'GH_TOKEN')]) {
        sh 'set +x; gh pr view --repo Local-Narx-Space/boutique-gitops "$(cat gitops-pr-url.txt)" --json number --jq .number > gitops-pr-number.txt'
    }
    def prUrl = readFile('gitops-pr-url.txt').trim()
    if (action == 'rollback' || params.TARGET == 'production') {
        boutiqueNotify(event: action == 'rollback' ? 'recovery_review' : 'approval_required', service: params.SERVICE, target: params.TARGET, prUrl: prUrl)
    }
    def number = readFile('gitops-pr-number.txt').trim()
    if (!(number ==~ /[1-9][0-9]*/)) { error('Missing GitOps PR number') }
    // Queue validation in its own job without holding up PR creation.
    build job: 'Release Operations/boutique-gitops-validate', wait: false, parameters: [string(name: 'PR_NUMBER', value: number)]
    archiveArtifacts artifacts: 'gitops-pr-url.txt,planned-change.diff', fingerprint: true
    echo "Deployment PR (validation follows): ${readFile('gitops-pr-url.txt').trim()}"
}
