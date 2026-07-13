import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "upstream_release.py"
SPEC = importlib.util.spec_from_file_location("upstream_release", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class UpstreamReleaseTests(unittest.TestCase):
    def test_no_matching_tags_is_an_idempotent_empty_result(self):
        self.assertEqual(MODULE.discover(["not-a-release", "v1.2.3"]), [])

    def test_discovers_stable_and_preview_independently(self):
        targets = MODULE.discover(
            [
                "sdvd-server-v1.4.0",
                "preview-1.5.0.124",
                "sdvd-server-v1.4.1",
                "preview-1.5.0.125",
            ]
        )
        self.assertEqual(
            [tag.name for tag in targets],
            ["sdvd-server-v1.4.1", "preview-1.5.0.125"],
        )

    def test_version_sort_is_numeric(self):
        targets = MODULE.discover(
            ["preview-1.5.0.9", "preview-1.5.0.125", "preview-1.5.0.12"]
        )
        self.assertEqual(targets[0].name, "preview-1.5.0.125")

    def test_manual_exact_tag_and_missing_tag(self):
        tags = ["sdvd-server-v1.4.1", "preview-1.5.0.125"]
        self.assertEqual(MODULE.discover(tags, "preview-1.5.0.125")[0].channel, "preview")
        with self.assertRaisesRegex(ValueError, "does not exist"):
            MODULE.discover(tags, "preview-1.5.0.126")
        with self.assertRaisesRegex(ValueError, "must match"):
            MODULE.discover(tags, "preview-1.5.0.125;echo pwned")

    def test_deterministic_branch_and_recommended_tag(self):
        preview = MODULE.parse_upstream_tag("preview-1.5.0.125")
        self.assertEqual(preview.branch, "sync/upstream-preview-1.5.0.125")
        self.assertEqual(
            preview.recommended_fork_tag,
            "sdvd-server-v1.5.0-preview.125-anxi.1",
        )

    def test_release_tag_normalization(self):
        self.assertEqual(
            MODULE.parse_fork_tag("sdvd-server-v1.5.0-preview.125-anxi.1"),
            {
                "version": "1.5.0-preview.125-anxi.1",
                "upstream_tag": "preview-1.5.0.125",
            },
        )
        self.assertEqual(
            MODULE.parse_fork_tag("sdvd-server-v1.4.1-anxi.2")["version"],
            "1.4.1-anxi.2",
        )
        with self.assertRaises(ValueError):
            MODULE.parse_fork_tag("v1.5.0-anxi.1")

    def test_patch_overlap_and_pr_idempotency(self):
        overlap = MODULE.overlap_files(
            ["tools/steam-service/SteamAuthService.cs", "ANXI_STEAM_SERVICE_PATCH.md"],
            ["tools/steam-service/SteamAuthService.cs", "README.md"],
        )
        self.assertEqual(overlap, ["tools/steam-service/SteamAuthService.cs"])
        self.assertEqual(MODULE.pr_action("123"), "update")
        self.assertEqual(MODULE.pr_action(""), "create")


if __name__ == "__main__":
    unittest.main()
