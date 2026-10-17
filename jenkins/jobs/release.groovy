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
