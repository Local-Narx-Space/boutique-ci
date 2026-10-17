// The Pipeline seed defaults to manual builds while initial delivery is configured.
def suppressBuilds = suppressAutomaticBuilds
def services = ['frontend','catalogue','cart','orders']
services.each { service ->
 multibranchPipelineJob("boutique-${service}") {
  branchSources {
   branchSource {
    source {
     github {
      id("boutique-${service}-trusted-main")
      credentialsId('github-read')
      repoOwner('subhankar12-spec')
      repository("boutique-${service}")
      repositoryUrl("https://github.com/subhankar12-spec/boutique-${service}")
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
['deploy-dev','deploy-qa','deploy-prod','rollback','gitops-validate','production-verify'].each { job ->
 def target = ['deploy-dev':'dev','deploy-qa':'staging','deploy-prod':'production'][job]
 pipelineJob("boutique-${job}") {
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
   } else if (job == 'production-verify') {
    stringParam('PR_NUMBER', '', 'Validated production promotion PR')
    stringParam('PR_HEAD_SHA', '', 'Exact validated PR head')
   }
  }
  definition {
   cpsScm {
    scm { git { remote { url('https://github.com/subhankar12-spec/boutique-ci.git'); credentials('github-read') }; branch('*/main') } }
    scriptPath("pipelines/${job}.Jenkinsfile")
    lightweight(true)
   }
  }
 }
}
