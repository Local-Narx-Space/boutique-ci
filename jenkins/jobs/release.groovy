// The Pipeline seed defaults to manual builds while initial delivery is configured.
def suppressBuilds = suppressAutomaticBuilds
[
 'Services': 'Application service build and release pipelines',
 'Deployments': 'Environment-specific promotion and deployment verification entry points',
 'Release Operations': 'Protected validation, production verification, and recovery operations',
 'Administration': 'Controller setup and access administration jobs'
].each { name, purpose ->
 folder(name) {
  description(purpose)
 }
}

def services = ['frontend','catalogue','cart','orders']
services.each { service ->
 multibranchPipelineJob("Services/boutique-${service}") {
  branchSources {
   branchSource {
    source {
     github {
      id("boutique-${service}-trusted-main")
      credentialsId('github-service-ci')
      repoOwner('Local-Narx-Space')
      repository("boutique-${service}")
      repositoryUrl("https://github.com/Local-Narx-Space/boutique-${service}")
      configuredByUrl(false)
      traits {
       gitHubBranchDiscovery { strategyId(3) }
       headWildcardFilter { includes('main'); excludes('') }
      }
     }
    }
    if (suppressBuilds) {
     strategy {
      defaultBranchPropertyStrategy {
       props {
        noTriggerBranchProperty { triggeredBranchesRegex('^$') }
       }
      }
     }
    }
   }
  }
  orphanedItemStrategy { discardOldItems { numToKeep(10) } }
  triggers { periodicFolderTrigger { interval('1d') } }
 }
}
['deploy-dev','deploy-qa','deploy-prod','rollback','gitops-validate','release-verify'].each { job ->
 def target = ['deploy-dev':'dev','deploy-qa':'staging','deploy-prod':'production'][job]
 def folder = target ? 'Deployments' : 'Release Operations'
 pipelineJob("${folder}/boutique-${job}") {
  description(target ? "${job}: immutable release PR and deployment verification; QA uses staging. Production requires PR review and merge." : "Protected release support: ${job}")
  // Job DSL replaces job properties on every seed run. Declare the Pipeline
  // inputs here too so API/downstream builds work before its next execution.
  parameters {
   if (target) { choiceParam('ACTION', ['promote','verify'], 'Request a release PR or verify a merged deployment') }
   if (target || job == 'rollback') {
    choiceParam('TARGET', target ? [target] : ['dev','staging','production'])
    choiceParam('SERVICE', ['frontend','catalogue','cart','orders'])
   }
   if (target) {
    stringParam('IMAGE', '', 'Immutable service image digest')
    stringParam('RELEASE_BUILD', '', 'Dev publishing build number')
    stringParam('GITOPS_COMMIT', '', 'Full merged GitOps commit for verification')
   } else if (job == 'rollback') {
    stringParam('GITOPS_COMMIT', '', 'Previous protected-main commit containing the known-good service image/chart')
   } else if (job == 'gitops-validate') {
    stringParam('PR_NUMBER', '', 'GitOps PR number to validate')
   } else if (job == 'release-verify') {
    stringParam('PR_NUMBER', '', 'Validated promotion PR for any environment')
    stringParam('PR_HEAD_SHA', '', 'Exact validated PR head')
   }
  }
  definition {
   cpsScm {
    scm { git { remote { url('https://github.com/Local-Narx-Space/boutique-ci.git'); credentials('github-read') }; branch('*/main') } }
    scriptPath("pipelines/${job}.Jenkinsfile")
    lightweight(true)
   }
  }
 }
}
