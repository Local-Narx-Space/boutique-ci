# Boutique CI for the local lab

This repository defines Jenkins pipelines for frontend, catalogue, cart and orders.
The existing Jenkins controller runs reviewed builds on the private build agent.

## Jenkins layout

Jenkins groups related entry points into four folders: **Services** contains
the four service build pipelines, **Deployments** contains the separate dev,
QA and production promotion pipelines, **Release Operations** contains
GitOps validation, production verification and rollback, and
**Administration** contains the seed and access-check jobs. Pipeline names
and responsibilities stay distinct; foldering makes them easier to find.

## Environment pipelines

| Job | Target |
| --- | --- |
| `Deployments/boutique-deploy-dev` | Dev |
| `Deployments/boutique-deploy-qa` | QA (`staging` namespace and GitOps directory) |
| `Deployments/boutique-deploy-prod` | Production |

Each entry point calls the same shared delivery logic. `ACTION=promote` opens
an immutable release PR; `ACTION=verify` checks its merged deployment. Targets
are fixed per job. Support jobs validate PRs, watch production merges and request
manual recovery. The old combined promote/verify jobs are retired.

## Release flow

A service main push triggers tests and image construction in parallel, followed
by parallel image scanning and SBOM generation. Jenkins publishes the immutable
image and versioned chart once, then queues delivery without waiting.

Dev and staging promotion PRs are validated before eligible automatic merges.
Argo CD deploys merged GitOps changes; Jenkins verifies the expected image,
rollout and functional smoke tests before advancing to the next environment.
Successful staging verification opens a production PR. Production requires human
merge, followed by deployment verification. Promotion never rebuilds an image.

| Directory | Purpose |
| --- | --- |
| `vars/` | Shared service pipeline and release/PR helpers |
| `pipelines/` | Promotion, verification, production merge watcher, rollback, validation and seed |
| `scripts/` | Authorization for automatic merges and production merge-state checks |
| `jenkins/jobs/` | Job DSL for the four services and release jobs |
| `jenkins/agents/` | Build-agent image and its restricted build context |
| `jenkins/scripts/` | Pinned agent-tool installer and live Jenkins pipeline validator |
| `tests/` | Release authorization, production merge, agent-tool and validator tests |

The shared library and seed use separately reviewed commit pins. Operational
release Jenkinsfiles load main. Keep job parameters in the seed DSL consistent
with their Jenkinsfiles. The seed preserves unrelated existing Jenkins jobs.

The current lab uses its existing manually configured controller. Source cleanup
does not migrate Jenkins home, credentials or installed plugins. Fresh-controller
Compose/JCasC templates and inactive AWS/ServiceNow build paths have been removed.
See [agent instructions](jenkins/agents/README.md) for future worker rebuilds.

## Checks

Run all retained Python regression tests:

```bash
python3 -m unittest discover -s tests -v
```

`jenkins/scripts/validate-pipelines.py` validates Declarative syntax against an
existing authenticated Jenkins controller. It does not start jobs or deploy.
Service tests, scans, publication, manifest validation and deployment verification
remain required release gates. Protect GitOps review/validation rules separately.


Release builds compare the checkout with the last successful build that actually
published this service's image. Docs, GitHub configuration, Jenkinsfile and known
repository metadata changes skip expensive release work and downstream promotion;
checkout, main ancestry validation and the source secret scan still run. Skipped
builds do not become the publication baseline. Unknown paths, missing history,
first releases, runtime/dependency/Dockerfile/Helm changes take the full path.
Rename detection is disabled so moving application inputs into docs still builds.
Keep this conservative non-release path list aligned with Docker build inputs.

## Required review and release continuation

Application, CI and platform changes require Code-S-12 code-owner approval and
passing PR checks. Generated dev/QA GitOps image-and-chart promotions merge
automatically after both required GitHub checks pass. Production, rollback and
configuration changes require human review and merge. A shared release-verify
watcher verifies the exact merged selection before requesting the next promotion.

The protected Jenkins validator allows automatic merging only for the configured
App bot's exact head on a generated dev/staging service branch. It checks the
complete file list, rejects renamed code/configuration, and parses the release
YAML to ensure only the selected service image and chart version change. It never
approves a PR or uses an administrator merge. Failed checks and merge conflicts
remain blocking.

`jenkins/policies/gitops-rulesets.json` separates three controls:
- Main checks/history: nobody, including the App, can bypass either required check.
- Main PR/review: humans require Code-S-12 approval. Only the Jenkins App has a
  PR-only review exemption; the protected validator limits its use to dev/QA.
- Generated promotion branches: only the App can create/update these heads, so
  developers cannot modify a bot PR after creation. Normal feature branches are
  unaffected. The App does not have repository-administration permission.

Apply the reviewed policy definitions only after this CI change merges and its
validator is active. Create the review and generated-branch rulesets first, then
update the existing main ruleset, retaining uninterrupted review/check enforcement.
Existing QA PRs can then be revalidated by Jenkins; no human approval of routine
QA promotions is needed. Cancel their obsolete waiting watchers before requeuing
to avoid duplicate verification jobs. Production remains human-reviewed.

Service SCM discovery/status reporting uses github-service-ci, scoped to the four
service repositories. Release PRs use the separately scoped gitops-release-app.
After merging CI changes, activate the reviewed SHA in the boutique-ci shared
library and seed SCM; run the seed with automatic builds enabled.
