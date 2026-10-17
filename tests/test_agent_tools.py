#!/usr/bin/env python3
"""Supply-chain regression checks without external downloads or credentials."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("tools", Path(__file__).parents[1] / "jenkins/scripts/install-agent-tools.py")
tools = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tools)


class VerifiedArtifactTests(unittest.TestCase):
    def test_checksum_rejects_altered_binary_before_installation(self):
        class Opener:
            def open(self, *args, **kwargs):
                return io.BytesIO(b"altered release bytes")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(tools.urllib.request, "build_opener", return_value=Opener()):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    tools.fetch(tools.TOOLS["kubectl"], Path(directory) / "download")

    def test_download_and_redirect_require_approved_verified_https_origins(self):
        for url in ["http://github.com/tool", "https://evil.example/tool",
                    "https://github.com.evil.example/tool", "https://token@github.com/tool"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                tools.trusted_url(url)

    def test_archive_tree_cannot_escape_install_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            archive_path = root / "bad.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                member = tarfile.TarInfo("kubeconform")
                member.type = tarfile.SYMTYPE
                member.linkname = "../../escaped"
                archive.addfile(member)
            with self.assertRaisesRegex(ValueError, "regular binary"):
                tools.install("kubeconform", tools.TOOLS["kubeconform"], archive_path, root)
            self.assertFalse((root / "escaped").exists())


if __name__ == "__main__":
    unittest.main()
