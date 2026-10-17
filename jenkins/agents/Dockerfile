# Build from boutique-ci root with --platform linux/amd64.
# The daemon belongs to this agent's isolated VM, never the controller host.
FROM docker:29.4.0-cli@sha256:2efe7c8e806b35050def6ba1ba0ddad67b521a0a6d37f4910b3d88f11b495d03 AS dockercli
# Official inbound agent 3391.va_37fa_a_305d6d, Debian Trixie, Java 21 JDK.
FROM jenkins/inbound-agent@sha256:64a27e807d216d527a7f5224e6ff9733b5cbd8650db3b5dfd0aea3b94949460f
USER root
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
# Signed fixed snapshots pin packages/transitive dependencies as well as tools.
ARG DEBIAN_SNAPSHOT=20261008T000000Z
RUN source /etc/os-release && test "$ID" = debian && test "$VERSION_CODENAME" = trixie \
    && rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*.sources \
    && printf 'deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://snapshot.debian.org/archive/debian/%s trixie main\ndeb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://snapshot.debian.org/archive/debian-security/%s trixie-security main\n' "$DEBIAN_SNAPSHOT" "$DEBIAN_SNAPSHOT" > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-yaml git curl ca-certificates jq openssl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins
COPY jenkins/scripts/install-agent-tools.py /usr/local/lib/boutique/install-agent-tools.py
RUN python3 /usr/local/lib/boutique/install-agent-tools.py --destination /opt/boutique-agent-tools \
    && python3 /usr/local/lib/boutique/install-agent-tools.py --destination /opt/boutique-agent-tools --verify-only \
    && docker --version && docker buildx version && java -version \
    && python3 -c 'import yaml' && openssl version
ENV PATH="/opt/boutique-agent-tools/bin:${PATH}"
USER jenkins
