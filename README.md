# Boutique Jenkins CI and GitOps delivery

One Jenkins controller with zero built-in executors runs reviewed main builds on
an inbound `trusted-release` agent. Each service has a Jenkinsfile calling the
version-pinned, sandboxed shared library. Independent service repositories remain.

The shared pipeline checks out source, runs a secret scan, validates/packages
Helm, runs a separate **Test** stage, builds the runtime image, scans it,
generates an SBOM and publishes a source-tagged image and chart to GHCR. Artifacts
include the immutable image digest, source commit, scan/SBOM and chart package.
Existing source tags/chart versions are not overwritten.

For application services, `DELIVER_TO_DEV=true` opens a GitOps PR via
`boutique-promote`. The publishing executor is released before the child runs.
Jenkins does not merge the PR or directly deploy application manifests.
The Jenkins manifest check validates the PR; protected review/merge and Argo CD
perform delivery. A published build is not proof of successful deployment.
Publishing does not wait for delivery. The full manifest matrix runs once on the
exact PR head in `boutique-gitops-validate`, rather than once before PR creation
and again as the required PR check.

| Job | Purpose |
| --- | --- |
| Pipeline seed | Run reviewed Job DSL; suppress automatic service builds during setup |
| Four service/main jobs | Test, scan, package, publish and optionally propose dev deployment |
| `boutique-promote` | Select a dev publishing build or copy the same image/chart from dev to staging, staging to production; open PR |
| `boutique-rollback` | Restore a service's prior image/chart from protected Git history through a PR |
| `boutique-gitops-validate` | Validate PR manifests with protected tools and report commit status; no separate executor |
| `boutique-verify` | Read Argo/rollout state and run functional smoke tests; archive reports |
| `boutique-platform/main` | Optional ServiceNow incident-adapter build |
| `boutique-infrastructure` | Optional AWS Terraform plan/approved apply on separately authorized infrastructure agent |

Promotion does not rebuild. Human review confirms preceding-environment smoke
results and database migration compatibility. Protect GitOps main with the
`boutique/gitops-validation` check and independent review. Use a separate bot identity
for PR creation; self-approval is not independent review.

The seed is **Pipeline from SCM**, pinned to a reviewed full CI commit, with
script path `pipelines/seed-release.Jenkinsfile`. Its
`SUPPRESS_AUTOMATIC_BUILDS` defaults to true. Old bootstrap/policy jobs are no
longer generated; the seed deliberately does not delete unrelated existing jobs.
Disable obsolete jobs before using the simplified flow.

Required credentials are `github-read`, `ghcr-publish`, `gitops-pr` and the
GitOps-scoped `gitops-checks` Secret text token for standard manifest statuses.
Verification additionally uses read-only environment kubeconfigs and public TLS
CA files. No artifact/evidence signing keys are required.
See [Jenkins setup](https://github.com/subhankar12-spec/boutique-platform/blob/main/docs/jenkins-setup.md)
and [the existing Debian/kind deployment guide](https://github.com/subhankar12-spec/boutique-platform/blob/main/docs/deploy-cicd-kind.md).

PR/fork discovery is disabled on the credentialed controller. Before enabling
untrusted builds, provide disposable isolated workers and ensure those jobs have
no publishing, GitOps-write, cluster or cloud credentials. A label, sandbox or
custom controller-role variable alone is not a security boundary.

The controller core/plugins and agent tools remain checksum-locked. Validate
changes with the isolated controller harness; it does not publish or deploy:

```bash
python3 jenkins/scripts/doctor.py
python3 jenkins/scripts/smoke-controller.py --directory /tmp/boutique-jenkins-check
```

The single-controller Compose profile is for a fresh install; it preserves the
previous release-home volume name and does not migrate a manually created Jenkins
container. Preserve existing homes and private credentials during upgrades.

See the [current CI/platform file map](https://github.com/subhankar12-spec/boutique-platform/blob/main/docs/repository-map.md) for core files, optional
exercises and the removed legacy components.

The ServiceNow adapter build is opt-in in the seed with
`ENABLE_INCIDENT_BRIDGE_BUILD=true`. If an earlier seed already created
`boutique-platform`, disable that Jenkins job when the integration is unused;
removedJobAction=IGNORE deliberately preserves existing jobs.

## Separate test and image stages

`Test` builds the service Dockerfile's `test` target, then runs it as a disposable
container with a writable temporary home. On rootful validation daemons it uses
the agent UID/GID; on rootless daemons it uses container UID/GID 0, which map to
the unprivileged daemon owner and allow writes to the agent-owned report mount.
This does not change application runtime users. The service's
`ci/test.sh` runs tests afresh and writes JUnit XML into
`test-reports/` through a report-only workspace mount. The agent and its private
Docker daemon must see that workspace at the same absolute path.
Jenkins publishes individual results and archives reports even when tests fail.
A nonzero runner exit fails the build; missing reports fail validation; unstable
test results also skip subsequent stages. `Build image` then builds the final
runtime target, whose Dockerfile no longer executes tests as build instructions.
Test containers receive no publication credentials. Integration tests and
post-deployment smoke checks remain separate.

Existing Jenkins installations need the **JUnit** plugin and its dependencies
before selecting this library revision. The fresh controller's checksum lock
includes it. Installing a plugin does not require replacing Jenkins home/JCasC.

See the [file-by-file CI audit](docs/file-audit.md) for every retained file, optional installation tools and validation boundaries.

Operational pipelines bind their request parameters explicitly into shell
environments. This matters on a job's first upstream-triggered run: Jenkins
can expose values through `params` before exporting them as shell variables.
Dev promotion also passes the verified archived image/source directly to its
helper; publishing builds can be reused without rebuilding the same commit.

Source-secret scanning runs Trivy in offline dependency-resolution mode. It
still scans source files (including POM files) for secrets, but does not query
Maven Central to identify dependencies for this secret-only stage. The runtime
image vulnerability/secret scan remains unchanged. Respect repository Retry-After
responses; later Maven dependency downloads still require repository access.

Runtime image construction and unit tests run in parallel on the same checked-out
commit. Image scanning and SBOM generation also run in parallel. Publication
waits for every branch to pass; no additional Jenkins executors are requested.
Release evidence is archived once, including when a stage fails.
