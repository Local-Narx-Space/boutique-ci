// Run only on a trusted release agent. Never bind this credential in PR builds.
def call(Map config = [:]) {
    if (env.BOUTIQUE_CONTROLLER_ROLE != 'release' || env.BOUTIQUE_SLACK_ENABLED != 'true') { return }
    try {
        writeFile file: '.boutique-slack-notify.py', text: libraryResource('boutique/slack_notify.py')
        withEnv(["NOTICE_EVENT=${config.event ?: 'pipeline_failed'}",
                 "NOTICE_SERVICE=${config.service ?: ''}", "NOTICE_TARGET=${config.target ?: ''}",
                 "NOTICE_PR_URL=${config.prUrl ?: ''}"]) {
            withCredentials([string(credentialsId: 'slack-delivery-webhook', variable: 'SLACK_WEBHOOK_URL')]) {
                int result = sh(returnStatus: true, script: 'set +x; python3 .boutique-slack-notify.py')
                if (result != 0) { echo 'WARNING: Slack delivery failed; inspect notification configuration.' }
            }
        }
    } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException interrupted) {
        throw interrupted
    } catch (Exception ignored) {
        echo 'WARNING: Slack notification unavailable; deployment result is unchanged.'
    }
}
