import importlib.util
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / ".github/scripts"))
SPEC = importlib.util.spec_from_file_location(
    "verify_auth_publication", ROOT / ".github/scripts/verify_auth_publication.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AuthPublicationTests(unittest.TestCase):
    def verify(self, override):
        labels = {
            "org.opencontainers.image.version": "1.5.0-preview.140-anxi.1",
            "org.opencontainers.image.revision": "b" * 40,
            "com.anxi-panel.upstream-revision": "a" * 40,
            "com.anxi-panel.source-tree-sha256": hashlib.sha256(b"archive").hexdigest(),
            "org.opencontainers.image.created": "2026-10-26T06:49:43Z",
        }
        labels.update(override)
        with (
            patch.object(MODULE, "pinned_upstream_revision", return_value="a" * 40),
            patch.object(MODULE.subprocess, "check_output", side_effect=["b" * 40, b"archive"]),
            patch.object(MODULE.subprocess, "run"),
        ):
            return MODULE.verify(ROOT, "sdvd-server-v1.5.0-preview.140-anxi.1", {"Config": {"Labels": labels}})

    def test_existing_source_identity_is_preserved(self):
        value = self.verify({})
        self.assertEqual(value["sourceRevision"], "b" * 40)
        self.assertEqual(value["buildDate"], "2026-10-26T06:49:43Z")

    def test_wrong_source_or_version_or_tree_cannot_be_promoted(self):
        for key in ("org.opencontainers.image.version", "org.opencontainers.image.revision",
                    "com.anxi-panel.upstream-revision", "com.anxi-panel.source-tree-sha256"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify({key: "wrong"})

    def test_missing_timezone_is_rejected(self):
        with self.assertRaises(ValueError):
            self.verify({"org.opencontainers.image.created": "2026-10-26T06:49:43"})

    def test_recovery_has_no_build_or_tag_mutation(self):
        workflow = (ROOT / ".github/workflows/recover-steam-service-publication.yml").read_text(encoding="utf-8")
        self.assertNotIn("docker/build-push-action", workflow)
        self.assertNotIn("git tag", workflow)
        self.assertIn("skopeo copy --preserve-digests", workflow)
        self.assertNotIn("imagetools create", workflow)
        self.assertIn("Refusing to replace an unrelated image reference", workflow)
        self.assertIn("original-index.json", workflow)

    def test_normal_publication_avoids_unsupported_attestation(self):
        workflow = (ROOT / ".github/workflows/publish-steam-service.yml").read_text(encoding="utf-8")
        self.assertIn("provenance: false", workflow)
        self.assertIn("sbom: false", workflow)


if __name__ == "__main__":
    unittest.main()
