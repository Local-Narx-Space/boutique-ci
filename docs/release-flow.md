# Release flow on the laptop and cloud

The laptop uses the same release controls and immutable artifacts as cloud. Its
single host is not an independent production failure domain.

## Normal release

1. A protected service main commit triggers its Jenkins Multibranch Pipeline.
   Tests, image security scan and SBOM run before image/chart publication. The
   service job queues delivery without waiting for GitOps validation and deployment.
2. The service job calls boutique-promote for dev. A generated GitOps PR contains
   only release selection and the service's versioned chart package.
3. boutique-gitops-validate uses protected validation scripts and validates the
   exact candidate head. With BOUTIQUE_RELEASE_AUTOMATION=true, an unchanged PR
   authored by the gitops-pr identity on jenkins/promote/dev/... or staging/...
   can merge automatically. Other branches, rollback and production are excluded.
   Code/configuration changes and other service charts cannot auto-merge.
   GitHub's merge API receives the validated head SHA and enforces branch rules;
   no administrator bypass is requested. Conflicts or missing approvals stop it.
   This required PR check is the full manifest validation; promotion does not run
   the same matrix a second time before it opens the PR.
4. Argo CD automatically syncs the merged Git state and self-heals drift.
5. Validation queues boutique-verify with the exact merge commit, image and
   service. Verification waits for Argo reconciliation and all four deployments,
   checks the expected digest, and executes the real synthetic smoke suite. The
   rollout wait allows 15 minutes for the approved progressive checks to finish.
6. Only successful dev verification queues promotion of that digest to staging.
   The promotion fails if dev has meanwhile moved to a different digest.
   Staging follows the same validation, merge, sync and verification path.
7. Only after staging deployment and smoke verification succeed, Jenkins opens a
   production promotion PR for that exact staging digest. Production copies the
   selected artifact without rebuilding. A human reviews and merges the PR; Argo
   deploys after merge. After successful validation, boutique-production-verify waits for the unchanged
   generated production PR to merge, then queues boutique-verify with its merge
   SHA and exact production image. It never approves or merges the PR. Closing
   without merge queues nothing; a changed head fails closed and requires fresh
   validation. The watcher releases its executor between API polls and expires
   after seven days. Rerun validation to rearm an expired watcher. Duplicate
   validation runs can queue duplicate verifications; each is read-only apart
   from the existing synthetic smoke data. Rollbacks and non-generated production
   changes still require manual verification. Changing global Jenkins environment
   settings is not a reliable cancellation mechanism for an already-running build;
   explicitly cancel active watchers in Jenkins when suspending delivery.
8. Rollback remains a reviewed GitOps PR, never a mutable image overwrite.

Jobs queue downstream verification without waiting while holding an executor.
Verification also queues promotion without waiting, preventing executor deadlocks.
A service publishing build queues dev delivery; downstream job history and
verification reports are separate evidence. Publishing success is not a claim
that staging or production verification succeeded.

## One-time activation and bootstrap

Keep BOUTIQUE_RELEASE_AUTOMATION unset until these prerequisites are met:

- Bootstrap all four services in dev and staging to valid published digests;
  prepare production selections before registering its auto-sync Application.
  Never sync bootstrap image tags or omit required namespace secrets.
- Apply applications/laptop-projects.yaml and applications/laptop-appset.yaml
  from boutique-gitops. The ApplicationSet generates dev/staging/production. Dev
  auto-syncs; enable staging/production autoSync only when prerequisites pass.
  Commit and reapply the ApplicationSet when changing that bootstrap setting.
  Enabled environments sync automatically, prune removed managed resources and
  correct drift. No root app is required.
- Configure Jenkins Secret File credentials kubeconfig-dev, kubeconfig-staging,
  kubeconfig-production. Use restricted verification identities: get the relevant
  Argo Application, get/list/watch deployments and replicasets in that namespace.
  Never grant cluster-admin for verification. From the agent container the API
  address must be reachable with a valid certificate; a host-loopback endpoint
  in ~/.kube/config will not work unchanged. Protect these files as credentials.
- Configure Jenkins environment variables:

  ```text
  BOUTIQUE_DEV_ORIGIN=https://dev-boutique.narx.space
  BOUTIQUE_STAGING_ORIGIN=https://staging-boutique.narx.space
  BOUTIQUE_PRODUCTION_ORIGIN=https://shop.narx.space
  ```

- Publicly trusted HTTPS uses system CAs. For private CA deployments set
  BOUTIQUE_USE_PRIVATE_CA=true and supply boutique-ca-{environment} Secret Files.
  Certificate verification is never disabled.
- Complete the read-only rollout and smoke verification manually once in each
  environment before enabling automatic advancement. Smoke tests create isolated
  synthetic sessions/orders; allow for that data in your operational procedures.
- GitHub main protection: require boutique/gitops-validation and code-owner
  review. Use a pull-request ruleset with required approvals set to zero and required
  code-owner review enabled, so only code-owner-covered paths need approval.
  If the classic protection UI cannot express this combination, use a ruleset;
  do not remove production review to make automation pass. Confirm enforcement
  with both a generated dev PR and a production PR before activation. CODEOWNERS retains human ownership for production,
  scripts and configuration; generated dev/staging release selections explicitly
  have no owners. Do not enable blanket review requirements that block every
  automated release. Use a separate bot identity for PR creation so the human
  owner can approve production; GitHub forbids approving your own PR.
- Keep gitops-pr as Username/Password with repository Contents and Pull requests
  write. gitops-checks remains Secret Text with read access plus Commit statuses
  write. GitHub permissions and branch protection must be configured separately;
  these repository changes do not create external rules or credentials.
- Configure GitHub push webhooks to Jenkins /github-webhook/. Run the seed with
  SUPPRESS_AUTOMATIC_BUILDS=false after bootstrap, so main pushes trigger builds.
  Authenticated source status reporting needs a token/App permitted to write
  source commit statuses; the earlier github-read-only 403 is a separate issue.
- Finally set BOUTIQUE_RELEASE_AUTOMATION=true in Jenkins global environment.
  This is a bootstrap switch, not a per-release parameter. Existing operational
  jobs load their Jenkinsfiles from main; the shared library remains explicitly
  pinned and should be upgraded only after review.

The seed declares release-job parameters as well as their Jenkinsfiles, so a
first API build or a seed rerun remains parameterized. When changing a Pipeline's
inputs, update its matching entry in `jenkins/jobs/release.groovy` too. The locked
controller smoke check validates the generated parameter types, choices and defaults.

The activation work above requires the laptop/Jenkins/GitHub administrator. Cloud
workspace validation does not establish connectivity to the laptop or prove its
live release flow. Run a small release end to end and retain verification reports.

## Validation of this change

Python authorization regression tests cover bot identity, head changes, forks,
closed/draft PRs, path scope, staging, and exclusion of production and rollback.
Changed Groovy files compile; embedded shell scripts pass bash syntax checks.
The laptop Application manifests were parsed and checked for automatic policies.
These checks are not a live Jenkins/GitHub/Kubernetes integration test.


## Production watcher rollout

Review this CI change, then pin the existing seed job to its reviewed full commit
and run with SUPPRESS_AUTOMATIC_BUILDS=true to create boutique-production-verify
without activating service triggers. Preserve the shared-library pin. Operational
Jenkinsfiles use main; the watcher needs no new credentials or write permissions.
Enable automation only after the protection and identity checks above. Successful
validation must occur while automation is enabled to arm the watcher. Review the
watcher build and its downstream boutique-verify reports as separate evidence.

GitHub ruleset reference: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets

## Independent GitHub App promotion identity

Install the release App on boutique-gitops only, with Contents and Pull requests
write and Metadata read. Keep the GitOps validation-status token separate. Add a
new Jenkins GitHub App credential `gitops-release-app`, using a specific owner and
repository access strategy. Do not overwrite existing credentials during migration.

After the reviewed CI/library revision is installed and the App credential is
verified on the agent, select it through Jenkins global environment:

```text
BOUTIQUE_GITOPS_PR_CREDENTIAL=gitops-release-app
BOUTIQUE_GITOPS_BOT_LOGIN=boutique-jenkins-bot[bot]
BOUTIQUE_GITOPS_APP_ID=5354383
BOUTIQUE_GITOPS_BOT_ID=343828366
```

Unset selection preserves the previous `gitops-pr` behavior. App selection avoids
`GET /user`, which requires a human token. Automatic promotion checks both the bot
login/type and numeric actor ID, plus the Jenkins credential username against
the configured App ID, in
addition to existing unchanged-head, repository, branch and path restrictions.
Neither configuration nor identity verification enables release automation.
Production and rollback remain human-reviewed. Never grant the App administration
or review-bypass access. Verify protected-path review and generated-path behavior
on an isolated branch before changing main protection.
