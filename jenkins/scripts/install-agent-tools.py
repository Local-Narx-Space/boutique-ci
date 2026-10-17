#!/usr/bin/env python3
"""Install pinned official Linux amd64 tools; verify bytes before extraction.

Release SHA256/SHA512 values below were checked against publisher checksums.
Versions and hashes change together through review, never by following latest.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request

TOOLS = {
    "helm": dict(version="3.22.0", url="https://get.helm.sh/helm-v3.22.0-linux-amd64.tar.gz", sha256="1e4ab49e429626cf6c6958d914248b78c9730803c2751b87627e171dc800e7bb", kind="tar", member="linux-amd64/helm", args=["version", "--short"]),
    "kubectl": dict(version="1.34.0", url="https://dl.k8s.io/release/v1.34.0/bin/linux/amd64/kubectl", sha256="cfda68cba5848bc3b6c6135ae2f20ba2c78de20059f68789c090166d6abc3e2c", kind="binary", args=["version", "--client=true"]),
    "kubeconform": dict(version="0.6.7", url="https://github.com/yannh/kubeconform/releases/download/v0.6.7/kubeconform-linux-amd64.tar.gz", sha256="95f14e87aa28c09d5941f11bd024c1d02fdc0303ccaa23f61cef67bc92619d73", kind="tar", member="kubeconform", args=["-v"]),
    "trivy": dict(version="0.75.0", url="https://github.com/aquasecurity/trivy/releases/download/v0.75.0/trivy_0.75.0_Linux-64bit.tar.gz", sha256="c6e65abddb348e25f10549df887045629cf28cc72453cd1c63acb717316b3f3f", kind="tar", member="trivy", args=["--version"]),
    "syft": dict(version="1.54.1", url="https://github.com/anchore/syft/releases/download/v1.54.1/syft_1.54.1_linux_amd64.tar.gz", sha256="c069905b391cc4c20a5ba65ad5c10be2a7ba074f8ea6ad203e24d14e303dad47", kind="tar", member="syft", args=["version"]),
    "gh": dict(version="2.102.0", url="https://github.com/cli/cli/releases/download/v2.102.0/gh_2.102.0_linux_amd64.tar.gz", sha256="bb766f710eef8ede859c18578c72c327597cd4c8a85b06001b1f3843c6019386", kind="tar", member="gh_2.102.0_linux_amd64/bin/gh", args=["--version"]),
}
ORIGINS = {"get.helm.sh","dl.k8s.io", "cdn.dl.k8s.io", "github.com",
           "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


def trusted_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ORIGINS or parsed.username or parsed.password:
        raise ValueError("Artifact URL must use an approved official HTTPS origin")


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def digest_file(path, algorithm="sha256"):
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(tool, path):
    trusted_url(tool["url"])
    opener = urllib.request.build_opener(OfficialRedirects())
    with opener.open(tool["url"], timeout=60) as response, path.open("wb") as output:
        shutil.copyfileobj(response, output)
    algorithm = "sha512" if "sha512" in tool else "sha256"
    if digest_file(path, algorithm) != tool[algorithm]:
        raise ValueError("Official tool artifact checksum mismatch")


def install(name, tool, archive_path, root):
    executable = root / "bin" / name
    if tool["kind"] == "binary":
        shutil.copyfile(archive_path, executable)
    elif tool["kind"] == "tar":
        with tarfile.open(archive_path) as archive:
            member = archive.getmember(tool["member"])
            if not member.isfile():
                raise ValueError("Expected regular binary archive member")
            with archive.extractfile(member) as source, executable.open("wb") as output:
                shutil.copyfileobj(source, output)
    else:
        raise ValueError("Unsupported artifact kind")
    executable.chmod(0o755)
    return executable


def verify(root, manifest):
    for name, row in manifest.items():
        executable = root / "bin" / name
        if digest_file(executable) != row["installed_sha256"]:
            raise ValueError("Missing or changed installed tool: " + name)
        result = subprocess.run([str(executable), *TOOLS[name]["args"]], capture_output=True, text=True, timeout=30, check=True)
        if TOOLS[name]["version"] not in result.stdout + result.stderr:
            raise ValueError("Unexpected tool runtime version: " + name)
        print(name + " " + TOOLS[name]["version"] + " verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--only", nargs="+", choices=sorted(TOOLS), default=list(TOOLS))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        parser.error("These reviewed artifacts support Linux amd64 only")
    root = args.destination.resolve()
    manifest_path = root / "tools-manifest.json"
    if args.verify_only:
        manifest = json.loads(manifest_path.read_text())
        if set(manifest) != set(args.only):
            raise ValueError("Installed tool set differs from requested set")
        verify(root, manifest)
        return
    (root / "bin").mkdir(parents=True, exist_ok=True)
    manifest = {}
    with tempfile.TemporaryDirectory(prefix="verified-agent-tools-") as temporary:
        for name in args.only:
            tool = TOOLS[name]
            artifact = Path(temporary) / name
            fetch(tool, artifact)
            executable = install(name, tool, artifact, root)
            artifact.unlink()
            manifest[name] = {"version": tool["version"], "url": tool["url"], "installed_sha256": digest_file(executable)}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    verify(root, manifest)


if __name__ == "__main__":
    main()
