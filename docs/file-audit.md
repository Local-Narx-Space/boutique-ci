# CI repository file audit

Audited on 2026-10-14 against the single-controller delivery flow. This lists
every tracked file, including this audit. Required means used by the current
supported setup; it does not mean you must run every helper to deploy locally.
No previous signed-delivery workflow or validation controller remains.

## Folders

| Folder | Role | When needed |
| --- | --- | --- |
| `.github/` | Code ownership | Protecting reviewed CI changes; GitHub rules must enforce review |
| `vars/` | Jenkins shared-library entry points | Every service build and deployment PR |
| `pipelines/` | Seed, promotion, rollback, manifest check and verifier | Delivery; verifier needs target-host credentials |
| `jenkins/jobs/` | Job DSL | Creating/updating Jenkins jobs through the Pipeline seed |
| `jenkins/agents/` | Common inbound build-agent image | Building/rebuilding your agent; existing agents can continue running |
| `jenkins/controller/`, `jenkins/casc/` | Fresh controller image/configuration | New installations and reproducible configuration checks |
| `jenkins/scripts/` | Installation, diagnostics, tests and upgrade tools | Bootstrap, troubleshooting and maintenance |
| `docs/` | This audit | Understanding and reviewing repository scope |

The old separate root `scripts/` folder has been removed; plugin-lock maintenance
now lives alongside the other Jenkins tools. Local `.env`, plugin caches and
private migration state are ignored runtime files, not source folders to deploy.
Preserve existing Jenkins homes and private state during upgrades.

## Every tracked file

| File | Why retained | Category |
| --- | --- | --- |
| [.github/CODEOWNERS](../.github/CODEOWNERS) | Names the reviewer for CI changes; effective only with protection rules | Governance |
| [.gitignore](../.gitignore) | Excludes credentials, caches/logs and retired private-key files during migration | Source hygiene |
| [LICENSE](../LICENSE) | MIT usage/distribution terms | Repository metadata |
| [README.md](../README.md) | Current delivery flow and starting instructions | Documentation |
| [docs/file-audit.md](file-audit.md) | Complete inventory, findings and validation boundaries | Documentation |
| [vars/servicePipeline.groovy](../vars/servicePipeline.groovy) | Tests/JUnit, Helm checks, runtime build, image scanning/SBOM and publication | Core delivery |
| [vars/releaseArtifact.groovy](../vars/releaseArtifact.groovy) | Copies the publishing build's exact image/chart/source artifacts for dev selection | Core delivery |
| [vars/gitopsPullRequest.groovy](../vars/gitopsPullRequest.groovy) | Opens promotion/rollback PRs and queues manifest validation without waiting | Core delivery |
| [pipelines/seed-release.Jenkinsfile](../pipelines/seed-release.Jenkinsfile) | Pipeline seed; nine default jobs, optional tenth adapter build | Bootstrap |
| [pipelines/promote.Jenkinsfile](../pipelines/promote.Jenkinsfile) | Opens dev selection or same-artifact staging/production promotion PR | Core delivery |
| [pipelines/rollback.Jenkinsfile](../pipelines/rollback.Jenkinsfile) | Restores one service from protected GitOps history through a PR | Recovery |
| [pipelines/gitops-validate.Jenkinsfile](../pipelines/gitops-validate.Jenkinsfile) | Runs protected manifest tools on candidate inputs and reports the required commit status | Core delivery |
| [pipelines/verify.Jenkinsfile](../pipelines/verify.Jenkinsfile) | Checks Argo/rollout and runs smoke tests, archiving operational reports | Optional automation; live verification itself is required |
| [jenkins/jobs/release.groovy](../jenkins/jobs/release.groovy) | Main-only application discovery and deployment/optional AWS job definitions | Bootstrap |
| [jenkins/agents/Dockerfile](../jenkins/agents/Dockerfile) | Java Remoting, private-daemon Docker CLI and reviewed CI/deployment tools | Agent installation |
| [jenkins/agents/Dockerfile.dockerignore](../jenkins/agents/Dockerfile.dockerignore) | Restricts the agent build context to its build definition and tool installer | Build hygiene |
| [jenkins/agents/README.md](../jenkins/agents/README.md) | Agent build, secret-file WebSocket connection and workspace/socket requirements | Installation documentation |
| [jenkins/controller/Dockerfile](../jenkins/controller/Dockerfile) | Pinned Jenkins core, verified plugins and fresh-install JCasC | Optional fresh controller |
| [jenkins/controller/Dockerfile.dockerignore](../jenkins/controller/Dockerfile.dockerignore) | Restricts the controller build context; excludes `.env`, keys, caches and agent files | Build hygiene |
| [jenkins/controller/plugins.lock.json](../jenkins/controller/plugins.lock.json) | Official checksums, versions, origins and dependency records for core/plugins | Reproducibility |
| [jenkins/controller/plugins.txt](../jenkins/controller/plugins.txt) | Readable plugin/version list, checked against the checksum lock by doctor.py | Installation/maintenance |
| [jenkins/casc/jenkins.yaml](../jenkins/casc/jenkins.yaml) | Zero controller executors, local users/authorization, environment and pinned untrusted library | Optional fresh controller |
| [jenkins/compose.yaml](../jenkins/compose.yaml) | Starts the fresh loopback controller with its persistent home | Optional fresh controller |
| [jenkins/scripts/init-local.sh](../jenkins/scripts/init-local.sh) | Generates missing local credentials/library pin while preserving existing `.env` values | Optional fresh-controller bootstrap |
| [jenkins/scripts/install-agent-tools.py](../jenkins/scripts/install-agent-tools.py) | Seven pinned tools: Helm, kubectl, Terraform, kubeconform, Trivy, Syft and gh | Agent installation |
| [jenkins/scripts/install-locked-plugins.py](../jenkins/scripts/install-locked-plugins.py) | Downloads or verifies official core/plugin artifacts before use | Controller installation/validation |
| [jenkins/scripts/doctor.py](../jenkins/scripts/doctor.py) | Checks plugin declarations, Java and optional artifact/network prerequisites | Diagnostics |
| [jenkins/scripts/smoke-controller.py](../jenkins/scripts/smoke-controller.py) | Disposable native Jenkins: plugins, JCasC, Job DSL, Declarative syntax and runtime gates | Configuration validation |
| [jenkins/scripts/validate-pipelines.py](../jenkins/scripts/validate-pipelines.py) | Authenticated native Declarative linter, used by the smoke harness; useful against an existing controller too | Configuration validation |
| [jenkins/scripts/test-agent-tools.py](../jenkins/scripts/test-agent-tools.py) | Rejects altered downloads, untrusted origins and non-regular archive members | Installer regression checks |
| [jenkins/scripts/test-runtime-tools.py](../jenkins/scripts/test-runtime-tools.py) | Checks checksum/dependency integrity and credential-safe redirects | Installer/linter regression checks |
| [jenkins/scripts/lock-plugins.py](../jenkins/scripts/lock-plugins.py) | Creates a checksum-verified lock from a reviewed, working plugin set | Upgrade maintenance; not a build-time dependency |

## Cleanup and deliberate choices

Removed `lockable-resources`: no remaining pipeline uses its lock step and no
retained plugin requires it. The remaining 79 plugins are eight direct features
and their required dependency closure: JCasC, Copy Artifact, GitHub Branch Source,
Job DSL, JUnit, Matrix Authorization, Timestamper and the standard Pipeline bundle.
Some dependency names do not appear in Groovy; deleting them would break plugins.
The Pipeline bundle includes milestone support as a required dependency.

Removed agent Go/Maven downloads and unused whole-tree extraction support.
Service Dockerfile test/build environments already supply those language tools.
Java 21 remains required for Remoting. Python runs orchestration scripts; PyYAML
reads configuration. Docker/buildx builds/runs containers; Helm/kubeconform check
manifests; Trivy/Syft scan and produce SBOMs; gh creates PRs/statuses. kubectl
supports verification. Terraform and AWS CLI support the optional AWS worker;
AWS CLI also authenticates AWS kubeconfigs. Separate workers still need separate
identities; sharing an image does not imply sharing credentials.

Both controller and agent Dockerfile-specific context filters are retained.
The two plugin manifests are complementary: JSON is the verified installation
contract; TXT is the readable version list. Existing manually installed Jenkins
must not be replaced with fresh JCasC merely to update a shared-library pin.

## Validation and limits

```bash
python3 jenkins/scripts/test-agent-tools.py
python3 jenkins/scripts/test-runtime-tools.py
python3 jenkins/scripts/doctor.py
python3 jenkins/scripts/smoke-controller.py --directory /tmp/boutique-ci-audit
```

The audit checks all Python/shell syntax, Markdown links, Compose structure,
Dockerfile definitions and the plugin dependency graph. Native Jenkins validates
all retained plugins, JCasC, actual sandboxed Job DSL with zero custom method
approvals and Declarative pipelines; isolated
runtime fixtures check downstream failure propagation and JUnit pass/fail/unstable
gates. These fixtures use no real GitHub/cloud/cluster credentials.

A Dockerfile definition check is not a full image build. The revised agent image
must be rebuilt and scanned on the target host; its signed Debian snapshot must
be reachable. The existing connected agent remains usable because removing
unused tools changes no pipeline requirement. The controller image/new-install
path must be accepted on its target host before replacing an installation.
Live GitHub/GHCR publication, Argo deployment, target worker connectivity and
notifications remain separate acceptance work. See the platform repository's
[current validation](https://github.com/subhankar12-spec/boutique-platform/blob/main/docs/validation.md)
and [deployment guide](https://github.com/subhankar12-spec/boutique-platform/blob/main/docs/deploy-cicd-kind.md).

The seed uses supported source/trait/branch-strategy DSL rather than deferred XML
configure blocks. Authorize Project must be installed and configured separately
on the controller to give this sandboxed seed a real operator identity; the
current 79-plugin image lock does not include it. Follow the platform Jenkins
setup guide for the seed Authorization sidebar page. Full-SHA seed checkout must
have Lightweight checkout disabled.

On 2026-10-16, the live frontend run exposed Docker buildx attempting to write
`/.docker` before the Test stage could start. Checkout now initializes a private
workspace Docker configuration directory for all later steps. A non-root native
Docker build reproduced the failure with `HOME=/` and passed with the writable
configuration path. This focused check is not a full service pipeline rerun.

A second live-run correction on 2026-10-16 handles rootless report ownership:
container UID/GID 0 map to the unprivileged daemon owner, while reusing the host
UID/GID maps into subordinate IDs. The test runner now selects 0:0 only for a
rootless daemon; rootful validation retains the agent UID/GID. Selector checks
covered both modes and an actual non-root rootful container wrote agent-owned
XML through the report mount. Rootless execution must still be confirmed on
the user's daemon; application runtime identities are unchanged.
