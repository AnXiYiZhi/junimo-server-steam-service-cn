import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "auth_upstream_source", ROOT / ".github/scripts/upstream_release.py"
)
SOURCE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SOURCE
SPEC.loader.exec_module(SOURCE)


class AuthUpstreamSourceTests(unittest.TestCase):
    def resolve(self, tag, revision):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "upstream-release.json"
            path.write_text(
                json.dumps({"upstreamTag": tag, "upstreamRevision": revision}),
                encoding="utf-8",
            )
            return SOURCE.pinned_upstream_revision(str(path), "preview-1.5.0.140")

    def test_deleted_preview_tag_keeps_reviewed_commit_identity(self):
        revision = "f318717ac06a780b6b21080b0263c16278d8e6e1"
        self.assertEqual(self.resolve("preview-1.5.0.140", revision), revision)

    def test_different_upstream_version_is_rejected(self):
        with self.assertRaises(ValueError):
            self.resolve("preview-1.5.0.125", "a" * 40)

    def test_revision_cannot_be_a_branch_or_injected_output(self):
        for value in ("master", "a" * 39, "A" * 40, "a" * 40 + "\nother=value", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.resolve("preview-1.5.0.140", value)

    def test_publish_retains_real_upstream_ancestry_gate(self):
        workflow = (ROOT / ".github/workflows/publish-steam-service.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('--manifest tools/steam-service/upstream-release.json', workflow)
        self.assertIn('merge-base --is-ancestor "$upstream_revision" "$RELEASE_SHA"', workflow)


if __name__ == "__main__":
    unittest.main()
