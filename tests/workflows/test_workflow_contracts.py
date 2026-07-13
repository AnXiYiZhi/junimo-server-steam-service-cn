import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


class WorkflowContractTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def test_sync_is_scheduled_and_keeps_channels_independent(self):
        workflow = self.read("sync-upstream-tag.yml")
        self.assertIn('cron: "17 */6 * * *"', workflow)
        self.assertIn("Select numeric latest tag per channel", workflow)
        self.assertIn("refs/upstream-tags/$TAG", workflow)
        self.assertIn("merge-base --is-ancestor", workflow)

    def test_sync_uses_real_merge_and_fails_conflicts(self):
        workflow = self.read("sync-upstream-tag.yml")
        self.assertIn('git merge --no-ff --no-edit "refs/upstream-tags/$TAG"', workflow)
        self.assertIn("git merge --abort", workflow)
        self.assertNotIn("git merge -Xours", workflow)
        self.assertNotIn("git merge -Xtheirs", workflow)
        self.assertNotIn("gh pr merge", workflow)

    def test_pr_is_updated_and_patch_overlap_is_labeled(self):
        workflow = self.read("sync-upstream-tag.yml")
        self.assertIn("gh pr list --state open", workflow)
        self.assertIn("gh pr edit", workflow)
        self.assertIn("gh pr create", workflow)
        self.assertIn("needs-anxi-patch-review", workflow)
        self.assertIn("auto-upstream-sync", workflow)
        self.assertIn("grep '^tools/steam-service/'", workflow)

    def test_safe_sync_auto_merge_requires_exact_validated_sha_and_labels(self):
        workflow = self.read("auto-merge-upstream-sync.yml")
        self.assertIn('workflows: ["Validate Upstream Sync"]', workflow)
        self.assertIn("workflow_run.conclusion == 'success'", workflow)
        self.assertIn("head_repository.full_name == github.repository", workflow)
        self.assertIn("current_sha", workflow)
        self.assertIn("VALIDATED_SHA", workflow)
        self.assertIn("grep -Fxq upstream-sync", workflow)
        self.assertIn("grep -Fxq auto-upstream-sync", workflow)
        self.assertIn("grep -Fxq needs-anxi-patch-review", workflow)
        self.assertIn("-f merge_method=merge", workflow)
        self.assertIn('-f sha="$VALIDATED_SHA"', workflow)
        self.assertNotIn("merge_method=squash", workflow)

    def test_sync_validation_has_no_private_secret_contract(self):
        workflow = self.read("validate-upstream-sync.yml")
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertIn("push", workflow)  # docker build is explicitly local only
        self.assertNotIn("docker/build-push-action", workflow)

    def test_publish_is_exact_tag_only_and_has_provenance(self):
        trigger = self.read("publish-tag.yml")
        workflow = self.read("publish-steam-service.yml")
        self.assertIn('"sdvd-server-v*-anxi.*"', trigger)
        self.assertNotIn('"v*-anxi.*"', trigger)
        self.assertIn("uses: ./.github/workflows/publish-steam-service.yml", trigger)
        self.assertIn("merge-base --is-ancestor", workflow)
        for label in (
            "org.opencontainers.image.source",
            "org.opencontainers.image.revision",
            "org.opencontainers.image.version",
            "org.opencontainers.image.created",
            "io.anxi.upstream.tag",
            "io.anxi.upstream.ref",
        ):
            self.assertIn(label, workflow)

    def test_merged_sync_is_revalidated_then_tagged_and_published(self):
        workflow = self.read("release-merged-upstream-sync.yml")
        self.assertIn("github.event.pull_request.merged == true", workflow)
        self.assertIn("contains(github.event.pull_request.labels.*.name, 'upstream-sync')", workflow)
        self.assertIn("Use 'Create a merge commit', not squash or rebase", workflow)
        self.assertLess(workflow.index("  validate:"), workflow.index("  tag:"))
        self.assertLess(workflow.index("  tag:"), workflow.index("  publish:"))
        self.assertIn("git/refs", workflow)
        self.assertIn("refusing to overwrite it", workflow)
        self.assertIn("uses: ./.github/workflows/publish-steam-service.yml", workflow)
        self.assertNotIn("SDVD_DOCKER_HOSTS", workflow)
        self.assertNotIn("STEAM_PASSWORD", workflow)

    def test_private_e2e_skips_before_checkout_when_fleet_is_absent(self):
        workflow = self.read("e2e-tests.yml")
        fleet = workflow.index("  fleet:")
        checkout = workflow.index("      - name: Checkout code", fleet)
        self.assertLess(fleet, checkout)
        self.assertIn("needs.fleet.outputs.configured == 'true'", workflow)
        self.assertIn("no keyscan, test run, or artifact upload was attempted", workflow)


if __name__ == "__main__":
    unittest.main()
