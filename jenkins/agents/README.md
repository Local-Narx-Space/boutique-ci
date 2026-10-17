# Local-lab Jenkins build agent

The retained Linux amd64 image provides Java 21, Docker CLI/buildx, Python/PyYAML,
Git, curl, jq, OpenSSL, Helm, kubectl, kubeconform, Trivy, Syft and GitHub CLI.
Base images and downloaded tools are pinned; Debian packages use a fixed signed
snapshot. Terraform and AWS CLI are no longer installed by this image definition.
Existing running agents may still contain older optional tools until rebuilt.

Build from the boutique-ci repository root when a worker rebuild is needed:

```bash
docker build --pull --platform linux/amd64 -f jenkins/agents/Dockerfile -t boutique-agent:local .
```

The Dockerfile-specific ignore file includes only the build definition and tool
installer. The build needs access to the pinned Debian snapshot and official tool
archives. The installer verifies downloaded checksums and installed tool versions:

```bash
python3 jenkins/scripts/install-agent-tools.py --destination /absolute/path/tools
python3 jenkins/scripts/install-agent-tools.py --destination /absolute/path/tools --verify-only
```

Service Go, Maven, Node and Python test environments are provided by the service
Dockerfiles. They are not installed on the common agent.

The current inbound agent uses label `trusted-release` and a private rootless
Docker daemon. Keep controller executors disabled. Test-report bind mounts require
the daemon and agent to see the workspace at the same absolute path and with the
same host owner. The service pipeline selects container UID 0 for rootless test
runners, mapping to the unprivileged daemon owner, while retaining dropped
capabilities and no-new-privileges. Runtime application users remain unchanged.

Agent connection secrets belong in private files outside checkouts. Remoting can
read a mounted file using `-secret @/run/secrets/agent-secret`; preserve the existing
WebSocket URL, workspace, secret file and socket mounts when replacing a worker.
Keep the Docker daemon isolated from the controller host. Verification uses scoped
Kubernetes credentials and application HTTPS origins. Untrusted PR builds require
separate disposable infrastructure without release credentials.

Source cleanup does not rebuild or restart the running agent. Verify a rebuilt
image and its service pipeline before replacing the existing worker.
