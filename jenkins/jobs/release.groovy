// The Pipeline seed defaults to manual builds while initial delivery is configured.
def suppressBuilds = suppressAutomaticBuilds
def services = ['frontend','catalogue','cart','orders']
if (enableIncidentBridgeBuild) {
 services << 'platform'
}
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
['promote','verify','rollback','gitops-validate','production-verify'].each { job ->
 pipelineJob("boutique-${job}") {
  // Job DSL replaces job properties on every seed run. Declare the Pipeline
  // inputs here too so API/downstream builds work before its next execution.
  parameters {
   if (job in ['promote','verify','rollback']) {
    choiceParam('TARGET', ['dev','staging','production'])
    choiceParam('SERVICE', ['frontend','catalogue','cart','orders'])
   }
   if (job == 'promote') {
    stringParam('IMAGE', '', 'Dev: published service digest. Other environments copy the preceding selection.')
    stringParam('RELEASE_BUILD', '', 'Dev only: service/main publishing build number')
   } else if (job == 'verify') {
    stringParam('IMAGE', '', 'Exact immutable image expected in the selected service')
    stringParam('GITOPS_COMMIT', '', 'Full reviewed GitOps merge commit')
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
pipelineJob('boutique-infrastructure') {
 definition { cpsScm {
  scm { git { remote { url('https://github.com/subhankar12-spec/boutique-infrastructure.git'); credentials('github-read') }; branch('*/main') } }
  scriptPath('Jenkinsfile'); lightweight(true)
 } }
}
