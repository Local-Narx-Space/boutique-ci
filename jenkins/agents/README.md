# Jenkins agents

The common Linux amd64 image contains Java 21 JDK, Docker 29.4.0 CLI/buildx,
Python/PyYAML, Git, OpenSSL, jq, AWS CLI, kubectl 1.34.0, kubeconform 0.6.7,
Helm 3.22.0, Terraform 1.11.4, Trivy 0.75.0, Syft 1.54.1 and GitHub CLI 2.102.0.
Base/CLI images are digest-pinned; Debian package
dependencies come from a fixed signed snapshot. Official tool archives have
reviewed SHA256/SHA512 pins checked before extraction, followed by executable
hash/version checks. Pins require reviewed updates and image scans; they do
not establish that an old version remains free of vulnerabilities.

The snapshot endpoint `snapshot.debian.org` must be reachable during image
builds. A failed download or Dockerfile definition check does not establish a
working image. Build and scan the complete image on your agent host and verify
its tools before using it for delivery. Cloud component checks are documented
in the platform repository's current validation guide.

To verify tools independently, run the installer and add its `bin` directory to PATH:

```bash
python3 jenkins/scripts/install-agent-tools.py --destination /absolute/path/tools
```

Java 21 is required for Jenkins Remoting, supplied by the inbound-agent base. `--verify-only` checks the stored executable
hashes and versions without downloads. Run
`python3 jenkins/scripts/test-agent-tools.py` for checksum, trusted-origin and
archive-traversal rejection checks. The Dockerfile-specific ignore file limits
its build context to the installer and build definition, excluding controller
credentials/configuration and Git.

Go, Maven, Node and application Python test dependencies live in the service
Dockerfile test targets. They do not need to be installed on the common agent.

The controller has zero executors. For reviewed main builds, create one private
inbound agent with label `trusted-release` and one executor. The Pipeline seed,
promotion, rollback and optional read-only verifier use the same label. An
optional `terraform-trusted` worker handles separately authorized AWS work.
PR/fork discovery is disabled. Before enabling arbitrary PRs, provision
disposable isolated workers without publishing, GitOps-write, cluster or cloud
credentials; never share their daemon/workspace with reviewed release work.
Labels and the Groovy sandbox are not credential/security isolation.

Build the common agent image from the `boutique-ci` repository root:

```bash
docker build --pull --platform linux/amd64 -f jenkins/agents/Dockerfile -t boutique-agent:local .
```

Build agents connect to a dedicated rootless Docker daemon owned by their user. Follow Docker's supported distribution instructions to start that daemon; mount its Unix socket into the agent and set `DOCKER_HOST` to the mounted socket. Mounting a Docker socket gives control over that daemon, even with a read-only bind mount. Never mount the controller host's rootful Docker socket. The optional Terraform worker does not need a Docker socket. GitOps manifest validation uses the same reviewed worker and protected tools; it never executes candidate shell/Jenkins scripts.

Docker-using container agents must mount their workspace at the same absolute path that the Docker daemon sees on its host. Integration checks bind configuration and temporary fixtures by that path. Alternatively, run the inbound agent directly on its dedicated VM. A private remote daemon without shared workspace files cannot run those bind-mounted checks.

## Connect locally over WebSocket

In Jenkins, create a permanent inbound node with one executor and the intended label. Save its generated agent secret in a mode-0600 file inside a private directory outside all checkouts. Set `BOUTIQUE_AGENT_SECRET_FILE` to that file and `BOUTIQUE_AGENT_WORKSPACE` to a private, writable directory dedicated to this node. The file and workspace must be readable/writable by the UID used below.

The controller Compose ports bind to loopback. On Linux, host networking lets a local agent container reach those ports. A host-gateway address cannot reach a listener bound only to loopback.

```bash
: "${BOUTIQUE_AGENT_SECRET_FILE:?Set the private agent-secret file path}"
: "${BOUTIQUE_AGENT_WORKSPACE:?Set the node private workspace path}"
: "${BOUTIQUE_AGENT_DOCKER_SOCKET:?Set the private rootless Docker socket path}"
test "$(stat -c %u "$BOUTIQUE_AGENT_DOCKER_SOCKET")" -ne 0
install -d -m 700 -o "$(stat -c %u "$BOUTIQUE_AGENT_DOCKER_SOCKET")" \
  -g "$(stat -c %g "$BOUTIQUE_AGENT_DOCKER_SOCKET")" "$BOUTIQUE_AGENT_WORKSPACE/.agent-home"
docker run --rm --name boutique-build-agent --network host \
  --user "$(stat -c %u "$BOUTIQUE_AGENT_DOCKER_SOCKET"):$(stat -c %g "$BOUTIQUE_AGENT_DOCKER_SOCKET")" \
  --cap-drop ALL --security-opt no-new-privileges:true \
  -e JAVA_TOOL_OPTIONS="-Xmx256m -Duser.home=/home/jenkins" \
  -e JENKINS_URL="${JENKINS_RELEASE_URL:-http://127.0.0.1:8091/}" \
  -e JENKINS_AGENT_NAME=boutique-build-agent \
  -e JENKINS_WEB_SOCKET=true \
  -e JENKINS_AGENT_WORKDIR="$BOUTIQUE_AGENT_WORKSPACE" \
  -e DOCKER_HOST=unix:///run/rootless-docker.sock \
  -v "$BOUTIQUE_AGENT_SECRET_FILE:/run/secrets/agent-secret:ro" \
  -v "$BOUTIQUE_AGENT_WORKSPACE:$BOUTIQUE_AGENT_WORKSPACE" \
  -v "$BOUTIQUE_AGENT_DOCKER_SOCKET:/run/rootless-docker.sock:ro" \
  -v "$BOUTIQUE_AGENT_WORKSPACE/.agent-home:/home/jenkins" \
  boutique-agent:local -secret @/run/secrets/agent-secret
```

The official entrypoint does not read a secret-file environment variable.
The explicit `-secret @/run/secrets/agent-secret` argument makes Remoting read
the mounted file without putting the secret value in Docker environment settings
or the host command line.

An optional untrusted worker needs isolated infrastructure, credentials and a separate private daemon/workspace before PR discovery is enabled. WebSocket mode needs no exposed TCP remoting port. Agent secrets are generated for Jenkins nodes; they are not GitHub tokens or registry credentials.

## Remote agents

Expose the controller through authenticated TLS infrastructure and configure `JENKINS_RELEASE_URL` with the externally reachable HTTPS URL before starting controller Compose. Remove `--network host` for remote agents and use their normal routed network. Import the actual organizational CA into the agent trust store when needed; do not disable certificate verification.

Optional read-only verification needs network access to the cluster API and application TLS origins. Terraform agents use short-lived workload/instance-role credentials and a route to private EKS endpoints. Configure scoped Jenkins identities and permissions, node restrictions, controller backups, and reviewed GitHub credentials before enabling real delivery. The image and controller smoke check validate tooling/configuration; they do not provision remote agent VMs.

For test report bind mounts, the agent workspace and rootless daemon must use
the same host owner. Container UID 0 maps to that unprivileged owner; an explicit
container UID equal to the host UID instead maps into the subordinate UID range.
The shared pipeline detects rootless mode and selects container UID/GID 0 for
test runners, retaining dropped capabilities and no-new-privileges. Runtime
application images retain their configured non-root users.

The shared service pipeline initializes a private writable HOME under Jenkins's
per-workspace temporary directory before running tools. XDG_CACHE_HOME and
TRIVY_CACHE_DIR point below that home, so numeric agent UIDs inheriting HOME=/
do not write into /.cache. The Docker credential directory remains separate
inside the checkout and is removed after the build. Cache files remain private
to the agent workspace; review storage usage during normal agent maintenance.
