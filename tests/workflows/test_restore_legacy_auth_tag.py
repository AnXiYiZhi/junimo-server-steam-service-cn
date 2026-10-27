import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("restore_legacy_auth_tag", ROOT / "tools/restore_legacy_auth_tag.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_FIXTURE = json.loads((ROOT / "tests/workflows/fixtures/legacy-auth-oci-labels.json").read_text(encoding="utf-8"))


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def response(raw, media=INDEX, status=200, expected=None):
    return MODULE.Response(status, {"Content-Type": media, "Docker-Content-Digest": expected or digest(raw)}, raw)


class FakeRegistry:
    def __init__(self, labels=None):
        values = OCI_FIXTURE["labels"].copy()
        values.update(labels or {})
        self.config = encode({"architecture": "amd64", "os": "linux", "config": {"Labels": values}})
        self.config_digest = digest(self.config)
        self.platform = encode({"schemaVersion": 2, "mediaType": MANIFEST,
                                "config": {"digest": self.config_digest, "size": len(self.config),
                                           "mediaType": "application/vnd.oci.image.config.v1+json"}, "layers": []})
        self.platform_digest = digest(self.platform)
        self.index = encode({"schemaVersion": 2, "mediaType": INDEX, "manifests": [
            {"digest": self.platform_digest, "mediaType": MANIFEST, "size": len(self.platform),
             "platform": {"architecture": "amd64", "os": "linux"}}]})
        self.index_digest = digest(self.index)
        self.current = encode({"schemaVersion": 2, "mediaType": INDEX, "manifests": []})
        self.current_digest = digest(self.current)
        self.legacy = None
        self.puts = []
        self.reads = []
        self.current_reads = 0
        self.latest_reads = 0
        self.mode = "normal"
        self.source_override = None
        self.platform_override = None

    def constants(self):
        return patch.multiple(MODULE, LEGACY_DIGEST=self.index_digest,
                              PLATFORM_DIGEST=self.platform_digest, CURRENT_DIGEST=self.current_digest)

    def manifest(self, ref, allow_missing=False, **kwargs):
        self.reads.append(("HEAD" if kwargs.get("head") else "GET", ref))
        if ref == MODULE.LEGACY_DIGEST:
            return self.source_override or response(self.index)
        if ref == MODULE.PLATFORM_DIGEST:
            return self.platform_override or response(self.platform, MANIFEST)
        if ref == MODULE.LEGACY_TAG:
            if self.legacy is None:
                return MODULE.Response(404, {"Content-Type": "application/json"}, b'{"errors":[{"code":"MANIFEST_UNKNOWN"}]}')
            return self.legacy
        if ref == MODULE.CURRENT_TAG:
            self.current_reads += 1
            if self.mode == "protected-changed" and self.current_reads > 1:
                return response(b'{"changed":true}')
            return response(self.current)
        if ref == "latest":
            self.latest_reads += 1
            if self.mode == "latest-missing" or self.mode == "latest-created" and self.latest_reads == 1:
                return MODULE.Response(404, {}, b"")
            if self.mode == "latest-changed" and self.latest_reads > 1:
                return response(b'{"changed":true}')
            return response(self.current)
        raise AssertionError("unexpected manifest reference")

    def blob(self, ref):
        if ref != self.config_digest:
            raise AssertionError("unexpected blob reference")
        return self.config

    def put_manifest(self, body):
        self.puts.append(body)
        if self.mode == "write-rejected":
            return MODULE.Response(403, {}, b"private-token-body")
        if self.mode != "uncertain-absent":
            self.legacy = response(body)
        if self.mode.startswith("uncertain"):
            raise MODULE.RestoreError("write response unavailable")
        if self.mode == "wrong-write-receipt":
            return response(b"", status=201, expected="sha256:" + "0" * 64)
        return response(b"", status=201, expected=self.index_digest)


class RestoreLegacyAuthTagTests(unittest.TestCase):
    def restore(self, registry):
        with registry.constants():
            return MODULE.restore(registry)

    def test_fixed_identity_matches_independently_captured_registry_fixture(self):
        self.assertEqual(MODULE.LEGACY_DIGEST, OCI_FIXTURE["indexDigest"])
        self.assertEqual(MODULE.PLATFORM_DIGEST, OCI_FIXTURE["platformDigest"])
        self.assertEqual(MODULE.LEGACY_SOURCE_REVISION, OCI_FIXTURE["tagCommit"])
        self.assertEqual(MODULE.LEGACY_VERSION, OCI_FIXTURE["labels"]["org.opencontainers.image.version"])
        self.assertEqual(MODULE.LEGACY_REVISION, OCI_FIXTURE["labels"]["org.opencontainers.image.revision"])
        self.assertEqual(MODULE.LEGACY_CREATED, OCI_FIXTURE["labels"]["org.opencontainers.image.created"])
        self.assertEqual(len(OCI_FIXTURE["tagCommit"]), 40)
        self.assertEqual(len(OCI_FIXTURE["labels"]["org.opencontainers.image.revision"]), 12)
        self.assertEqual(OCI_FIXTURE["tagCommit"][:12], OCI_FIXTURE["labels"]["org.opencontainers.image.revision"])

    def test_full_source_commit_cannot_replace_the_actual_short_oci_revision(self):
        registry = FakeRegistry({"org.opencontainers.image.revision": OCI_FIXTURE["tagCommit"]})
        with self.assertRaises(MODULE.RestoreError):
            self.restore(registry)
        self.assertEqual(registry.puts, [])

    def test_missing_tag_restores_identical_index_once(self):
        registry = FakeRegistry()
        proof = self.restore(registry)
        self.assertEqual(registry.puts, [registry.index])
        self.assertEqual(registry.legacy.body, registry.index)
        self.assertGreaterEqual(registry.current_reads, 2)
        self.assertIn(registry.index_digest, json.dumps(proof))

    def test_existing_same_digest_is_idempotent_without_put(self):
        registry = FakeRegistry()
        registry.legacy = response(registry.index)
        self.restore(registry)
        self.assertEqual(registry.puts, [])

    def test_existing_other_digest_is_never_replaced(self):
        registry = FakeRegistry()
        registry.legacy = response(b'{"foreign":true}')
        with self.assertRaises(MODULE.RestoreError):
            self.restore(registry)
        self.assertEqual(registry.puts, [])

    def test_original_index_bytes_must_match_the_pinned_digest(self):
        registry = FakeRegistry()
        registry.source_override = response(registry.index + b" ", expected=registry.index_digest)
        with self.assertRaises(MODULE.RestoreError):
            self.restore(registry)
        self.assertEqual(registry.puts, [])

    def test_original_index_media_type_cannot_be_downgraded(self):
        registry = FakeRegistry()
        registry.source_override = response(registry.index, MANIFEST)
        with self.assertRaises(MODULE.RestoreError):
            self.restore(registry)
        self.assertEqual(registry.puts, [])

    def test_missing_original_index_does_not_trigger_a_write(self):
        registry = FakeRegistry()
        registry.source_override = MODULE.Response(404, {}, b"")
        with self.assertRaises(MODULE.RestoreError):
            self.restore(registry)
        self.assertEqual(registry.puts, [])

    def test_config_version_revision_and_date_must_each_match(self):
        for key in ("org.opencontainers.image.version", "org.opencontainers.image.revision",
                    "org.opencontainers.image.created"):
            with self.subTest(key=key):
                registry = FakeRegistry({key: "wrong"})
                with self.assertRaises(MODULE.RestoreError):
                    self.restore(registry)
                self.assertEqual(registry.puts, [])

    def test_platform_bytes_and_config_blob_are_hash_checked(self):
        for component in ("platform", "config"):
            with self.subTest(component=component):
                registry = FakeRegistry()
                if component == "platform":
                    registry.platform_override = response(registry.platform + b" ", MANIFEST,
                                                          expected=registry.platform_digest)
                else:
                    registry.config += b" "
                with self.assertRaises(MODULE.RestoreError):
                    self.restore(registry)
                self.assertEqual(registry.puts, [])

    def test_index_must_identify_the_pinned_linux_amd64_platform(self):
        registry = FakeRegistry()
        raw = json.loads(registry.index)
        raw["manifests"][0]["platform"]["architecture"] = "arm64"
        registry.index = encode(raw)
        registry.index_digest = digest(registry.index)
        with self.assertRaises(MODULE.RestoreError):
            self.restore(registry)
        self.assertEqual(registry.puts, [])

    def test_protected_tag_change_is_detected_after_the_one_write(self):
        registry = FakeRegistry()
        registry.mode = "protected-changed"
        with self.assertRaises(MODULE.RestoreError):
            self.restore(registry)
        self.assertEqual(len(registry.puts), 1)

    def test_latest_state_and_digest_are_both_protected(self):
        for mode in ("latest-changed", "latest-created"):
            with self.subTest(mode=mode):
                registry = FakeRegistry()
                registry.mode = mode
                with self.assertRaises(MODULE.RestoreError):
                    self.restore(registry)
                self.assertEqual(len(registry.puts), 1)

    def test_consistently_missing_latest_remains_missing(self):
        registry = FakeRegistry()
        registry.mode = "latest-missing"
        self.restore(registry)
        self.assertEqual(registry.puts, [registry.index])

    def test_uncertain_write_is_reconciled_by_reads_only(self):
        registry = FakeRegistry()
        registry.mode = "uncertain-committed"
        self.restore(registry)
        self.assertEqual(registry.puts, [registry.index])

    def test_uncertain_uncommitted_write_stops_without_replaying_put(self):
        registry = FakeRegistry()
        registry.mode = "uncertain-absent"
        with self.assertRaises(MODULE.RestoreError):
            self.restore(registry)
        self.assertEqual(registry.puts, [registry.index])

    def test_rejected_write_stops_without_replay_or_response_body_exposure(self):
        registry = FakeRegistry()
        registry.mode = "write-rejected"
        with self.assertRaises(MODULE.RestoreError) as caught:
            self.restore(registry)
        self.assertEqual(registry.puts, [registry.index])
        self.assertNotIn("private-token-body", str(caught.exception))

    def test_mismatched_write_receipt_is_resolved_using_unchanged_bytes(self):
        registry = FakeRegistry()
        registry.mode = "wrong-write-receipt"
        proof = self.restore(registry)
        self.assertTrue(proof["writeResponseUncertain"])
        self.assertEqual(registry.puts, [registry.index])

    def test_safe_proof_has_no_credentials_request_urls_or_messages(self):
        proof = self.restore(FakeRegistry())
        text = json.dumps(proof).lower()
        for forbidden in ("authorization", "password", "token", "username", "https://", "message"):
            self.assertNotIn(forbidden, text)
        self.assertTrue(proof["singleWriteAtMost"])
        self.assertNotIn("writeAttempts", proof)
        for key, value in proof.items():
            with self.subTest(key=key):
                self.assertTrue(type(value) in (bool, int) or value == "" or
                                isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None)
                if type(value) is int:
                    self.assertTrue(key.endswith("Status"))


class RegistryTransportTests(unittest.TestCase):
    def test_authentication_uses_existing_credentials_only_at_the_trusted_realm(self):
        calls = []

        def transport(method, url, headers, body):
            calls.append((method, url, headers.copy()))
            if len(calls) == 1:
                return MODULE.Response(401, {"WWW-Authenticate": 'Bearer realm="https://dockerauth.cn-hangzhou.aliyuncs.com/auth",service="fixed-service"'}, b"")
            return MODULE.Response(200, {}, b'{"token":"private-token"}')

        client = MODULE.RegistryClient("private-user", "private-password", transport=transport)
        client.authenticate()
        self.assertEqual(len(calls), 2)
        self.assertNotIn("Authorization", calls[0][2])
        self.assertTrue(calls[1][2]["Authorization"].startswith("Basic "))
        self.assertEqual(parse_qs(urlparse(calls[1][1]).query)["scope"],
                         ["repository:" + MODULE.REPOSITORY + ":pull,push"])
        self.assertEqual(client._token, "private-token")
        self.assertEqual((client._username, client._password), ("", ""))

    def test_untrusted_authentication_challenge_never_receives_credentials(self):
        for realm in ("https://example.invalid/auth", "http://dockerauth.cn-hangzhou.aliyuncs.com/auth",
                      "https://private:password@dockerauth.cn-hangzhou.aliyuncs.com/auth",
                      "https://dockerauth.cn-hangzhou.aliyuncs.com:444/auth"):
            with self.subTest(realm=realm):
                calls = []

                def transport(method, url, headers, body):
                    calls.append(headers.copy())
                    return MODULE.Response(401, {"WWW-Authenticate": 'Bearer realm="' + realm + '"'}, b"")

                client = MODULE.RegistryClient("private-user", "private-password", transport=transport)
                with self.assertRaises(MODULE.RestoreError):
                    client.authenticate()
                self.assertEqual(len(calls), 1)
                self.assertNotIn("Authorization", calls[0])

    def test_blob_redirect_uses_fixed_oss_host_without_authorization(self):
        calls = []
        signed = "https://aliregistry.oss-cn-hangzhou.aliyuncs.com/object?Signature=private-signature"

        def transport(method, url, headers, body):
            calls.append((method, url, headers.copy()))
            if len(calls) == 1:
                return MODULE.Response(307, {"Location": signed}, b"")
            return MODULE.Response(200, {}, b"verified-config")

        client = MODULE.RegistryClient("private-user", "private-password", transport=transport)
        client._token = "private-registry-token"
        self.assertEqual(client.blob("sha256:" + "a" * 64), b"verified-config")
        self.assertEqual(len(calls), 2)
        self.assertIn("Authorization", calls[0][2])
        self.assertEqual(calls[1][0], "GET")
        self.assertEqual(calls[1][1], signed)
        self.assertFalse(any(key.lower() == "authorization" for key in calls[1][2]))

    def test_blob_rejects_untrusted_redirects_before_following_them(self):
        for target in ("https://example.invalid/config", "http://aliregistry.oss-cn-hangzhou.aliyuncs.com/config",
                       "https://aliregistry.oss-cn-hangzhou.aliyuncs.com:444/config",
                       "https://private:password@aliregistry.oss-cn-hangzhou.aliyuncs.com/config"):
            with self.subTest(target=target):
                calls = []

                def transport(method, url, headers, body):
                    calls.append(url)
                    return MODULE.Response(307, {"Location": target}, b"")

                client = MODULE.RegistryClient("private-user", "private-password", transport=transport)
                with self.assertRaises(MODULE.RestoreError):
                    client.blob("sha256:" + "a" * 64)
                self.assertEqual(len(calls), 1)

    def test_blob_does_not_follow_a_second_redirect(self):
        calls = []

        def transport(method, url, headers, body):
            calls.append(url)
            return MODULE.Response(307, {"Location": "https://aliregistry.oss-cn-hangzhou.aliyuncs.com/again"}, b"")

        client = MODULE.RegistryClient("private-user", "private-password", transport=transport)
        with self.assertRaises(MODULE.RestoreError):
            client.blob("sha256:" + "a" * 64)
        self.assertEqual(len(calls), 2)

    def test_put_is_one_request_even_when_the_response_is_lost(self):
        calls = []

        def transport(method, url, headers, body):
            calls.append((method, url, headers.copy(), body))
            raise URLError("private-response-detail")

        client = MODULE.RegistryClient("private-user", "private-password", transport=transport)
        with self.assertRaises(URLError):
            client.put_manifest(b"original-index")
        self.assertEqual(len(calls), 1)
        method, url, headers, body = calls[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(url, "https://" + MODULE.REGISTRY + "/v2/" + MODULE.REPOSITORY + "/manifests/" + MODULE.LEGACY_TAG)
        self.assertEqual(headers["Content-Type"], INDEX)
        self.assertEqual(body, b"original-index")

    def test_read_network_failures_stop_at_three_and_hide_error_details(self):
        calls = []
        secret = "private-password-should-not-escape"

        def transport(method, url, headers, body):
            calls.append(method)
            raise URLError(secret)

        client = MODULE.RegistryClient("private-user", secret, transport=transport, sleep=lambda _: None)
        with self.assertRaises(MODULE.RestoreError) as caught:
            client.read("GET", "https://" + MODULE.REGISTRY + "/v2/")
        self.assertEqual(calls, ["GET"] * 3)
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn("private-user", str(caught.exception))

    def test_transient_read_retries_but_not_forever(self):
        calls = []

        def transport(method, url, headers, body):
            calls.append(method)
            return MODULE.Response(503, {}, b"private-token-body")

        client = MODULE.RegistryClient("private-user", "private-password", transport=transport, sleep=lambda _: None)
        with self.assertRaises(MODULE.RestoreError) as caught:
            client.read("GET", "https://" + MODULE.REGISTRY + "/v2/")
        self.assertEqual(calls, ["GET"] * 3)
        self.assertNotIn("private-token-body", str(caught.exception))

    def test_deterministic_not_found_is_not_retried(self):
        calls = []

        def transport(method, url, headers, body):
            calls.append(method)
            return MODULE.Response(404, {}, b"private-body")

        client = MODULE.RegistryClient("private-user", "private-password", transport=transport, sleep=lambda _: None)
        self.assertEqual(client.read("HEAD", "https://" + MODULE.REGISTRY + "/v2/").status, 404)
        self.assertEqual(calls, ["HEAD"])


class LegacyRestoreWorkflowTests(unittest.TestCase):
    def test_workflow_uses_only_fixed_master_dispatch_and_registry_credentials(self):
        workflow = (ROOT / ".github/workflows/restore-legacy-auth-tag.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("inputs:", workflow)
        self.assertIn("refs/heads/master", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("secrets.ALIYUN_REGISTRY_USERNAME", workflow)
        self.assertIn("secrets.ALIYUN_REGISTRY_PASSWORD", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        source_guard = "git rev-parse 'refs/tags/v1.5.0-anxi.2^{}'"
        self.assertIn(source_guard, workflow)
        self.assertIn("'" + OCI_FIXTURE["tagCommit"] + "'", workflow)
        self.assertLess(workflow.index(source_guard), workflow.index("python3 tools/restore_legacy_auth_tag.py"))
        for forbidden in ("docker/build-push-action", "docker build", "gh release", "git tag", "packages: write"):
            self.assertNotIn(forbidden, workflow)


if __name__ == "__main__":
    unittest.main()
