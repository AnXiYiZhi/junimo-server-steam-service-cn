#!/usr/bin/env python3
"""Restore one missing ACR tag from its unchanged, already stored OCI index."""
import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


REGISTRY = "crpi-9z3bkb9g7fxeohrg.cn-hangzhou.personal.cr.aliyuncs.com"
REPOSITORY = "anxi-panel/junimo-steam-service-cn"
LEGACY_TAG = "1.5.0-anxi.2"
LEGACY_DIGEST = "sha256:99420ab30c09da019c425defd4d01796403ac03898ed261b9ee2a976f4bc6518"
PLATFORM_DIGEST = "sha256:34737f8b28e630a1d2994032bb158e577eb26bb5ba91683eae80770168db6da7"
LEGACY_VERSION = "1.5.0-anxi.2"
LEGACY_REVISION = "a6cee498f91b"
LEGACY_SOURCE_REVISION = "a6cee498f91b318cfcacf035b05b0644bd16829a"
LEGACY_CREATED = "2026-07-05T18:48:08Z"
CURRENT_TAG = "1.5.0-preview.140-anxi.1"
CURRENT_DIGEST = "sha256:4649205b292a89dee5073614408bc7fdbbe01886a597beb38d24e906ddba20f6"
INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
ACCEPT = ", ".join((INDEX_MEDIA_TYPE, MANIFEST_MEDIA_TYPE,
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.docker.distribution.manifest.v2+json"))
MAX_BYTES = 2 * 1024 * 1024
READ_ATTEMPTS = 3
TIMEOUT_SECONDS = 20
TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})
NETWORK_ERRORS = (urllib.error.URLError, OSError, TimeoutError)


class RestoreError(Exception):
    """A controlled error whose message never includes response data or secrets."""


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes


def header(response, name):
    return next((value for key, value in response.headers.items()
                 if key.lower() == name.lower()), "")


def sha256(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def document(raw):
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise RestoreError("registry returned invalid JSON") from None
    if not isinstance(result, dict):
        raise RestoreError("registry returned an invalid document")
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_transport(method, url, headers, body):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        response = opener.open(request, timeout=TIMEOUT_SECONDS)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise RestoreError("registry response exceeds the size limit")
        return Response(response.code, dict(response.headers), raw)


class RegistryClient:
    def __init__(self, username, password, transport=None, sleep=time.sleep):
        self._username = username
        self._password = password
        self._token = ""
        self._transport = transport or http_transport
        self._sleep = sleep

    def read(self, method, url, headers=None):
        if method not in {"GET", "HEAD"}:
            raise RestoreError("read operation must use GET or HEAD")
        for attempt in range(READ_ATTEMPTS):
            try:
                response = self._transport(method, url, headers or {}, None)
            except NETWORK_ERRORS:
                if attempt + 1 == READ_ATTEMPTS:
                    raise RestoreError("registry read failed after three attempts") from None
            else:
                if response.status not in TRANSIENT_STATUS:
                    return response
                if attempt + 1 == READ_ATTEMPTS:
                    raise RestoreError("registry read remained unavailable after three attempts")
            self._sleep(attempt + 1)
        raise RestoreError("registry read did not complete")

    def authenticate(self):
        challenge = self.read("GET", "https://" + REGISTRY + "/v2/")
        if challenge.status != 401:
            raise RestoreError("registry did not provide the expected authentication challenge")
        value = header(challenge, "www-authenticate")
        if not value.lower().startswith("bearer "):
            raise RestoreError("registry did not provide Bearer authentication")
        fields = dict(re.findall(r'([a-z]+)="([^"]*)"', value))
        realm = fields.get("realm", "")
        parsed = urllib.parse.urlparse(realm)
        if (parsed.scheme != "https" or parsed.hostname != "dockerauth.cn-hangzhou.aliyuncs.com"
                or parsed.port not in {None, 443} or parsed.username or parsed.password or parsed.fragment):
            raise RestoreError("registry authentication endpoint is not trusted")
        query = urllib.parse.urlencode({"service": fields.get("service", REGISTRY),
                                       "scope": "repository:" + REPOSITORY + ":pull,push"})
        credentials = base64.b64encode((self._username + ":" + self._password).encode()).decode()
        response = self.read("GET", realm + ("&" if parsed.query else "?") + query,
                             {"Authorization": "Basic " + credentials})
        if response.status != 200:
            raise RestoreError("registry authentication failed")
        raw = document(response.body)
        token = raw.get("token") or raw.get("access_token")
        if not isinstance(token, str) or not token:
            raise RestoreError("registry authentication did not return a token")
        self._token = token
        self._username = self._password = ""

    def manifest(self, ref, allow_missing=False, head=False):
        url = "https://" + REGISTRY + "/v2/" + REPOSITORY + "/manifests/" + urllib.parse.quote(ref, safe=":")
        response = self.read("HEAD" if head else "GET", url,
                             {"Accept": ACCEPT, "Authorization": "Bearer " + self._token})
        if response.status == 404 and allow_missing:
            return response
        if response.status != 200:
            raise RestoreError("manifest read returned HTTP " + str(response.status))
        return response

    def blob(self, digest):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise RestoreError("image config digest is invalid")
        response = self.read("GET", "https://" + REGISTRY + "/v2/" + REPOSITORY + "/blobs/" + digest,
                             {"Authorization": "Bearer " + self._token})
        if response.status in {302, 307}:
            location = header(response, "location")
            target = urllib.parse.urlparse(location)
            if (target.scheme != "https" or target.hostname != "aliregistry.oss-cn-hangzhou.aliyuncs.com"
                    or target.port not in {None, 443} or target.username or target.password or target.fragment):
                raise RestoreError("image config redirect is not trusted")
            # The signed OSS URL stays in memory. Never forward registry credentials.
            response = self.read("GET", location, {"Accept": "application/octet-stream"})
        if response.status != 200:
            raise RestoreError("image config read returned HTTP " + str(response.status))
        return response.body

    def put_manifest(self, body):
        # One write only. An uncertain response is resolved by read-back in restore.
        return self._transport("PUT", "https://" + REGISTRY + "/v2/" + REPOSITORY + "/manifests/" + LEGACY_TAG,
                               {"Content-Type": INDEX_MEDIA_TYPE, "Authorization": "Bearer " + self._token}, body)


def verify_manifest(response, expected):
    if response.status != 200 or header(response, "docker-content-digest") != expected or sha256(response.body) != expected:
        raise RestoreError("manifest bytes or digest do not match the fixed identity")
    return document(response.body)


def snapshot(client, ref, missing=False):
    response = client.manifest(ref, allow_missing=missing)
    if response.status == 404:
        return {"status": 404, "digest": ""}
    digest = header(response, "docker-content-digest")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None or sha256(response.body) != digest:
        raise RestoreError("protected reference has an invalid digest")
    return {"status": response.status, "digest": digest}


def restore(client):
    source = client.manifest(LEGACY_DIGEST)
    index = verify_manifest(source, LEGACY_DIGEST)
    if index.get("mediaType") != INDEX_MEDIA_TYPE or header(source, "content-type").split(";", 1)[0] != INDEX_MEDIA_TYPE:
        raise RestoreError("fixed source is not the original OCI index")
    entries = index.get("manifests")
    if not isinstance(entries, list):
        raise RestoreError("fixed source index has no platform list")
    platforms = [entry for entry in entries if isinstance(entry, dict)
                 and entry.get("platform", {}).get("os") == "linux"
                 and entry.get("platform", {}).get("architecture") == "amd64"]
    if len(platforms) != 1 or platforms[0].get("digest") != PLATFORM_DIGEST:
        raise RestoreError("fixed source has an unexpected linux amd64 platform")
    platform = verify_manifest(client.manifest(PLATFORM_DIGEST), PLATFORM_DIGEST)
    if platform.get("mediaType") != MANIFEST_MEDIA_TYPE:
        raise RestoreError("fixed platform is not an OCI image manifest")
    config_digest = platform.get("config", {}).get("digest", "")
    config_raw = client.blob(config_digest)
    if sha256(config_raw) != config_digest:
        raise RestoreError("image config bytes do not match their digest")
    config = document(config_raw)
    labels = config.get("config", {}).get("Labels", {})
    expected = {"org.opencontainers.image.version": LEGACY_VERSION,
                "org.opencontainers.image.revision": LEGACY_REVISION,
                "org.opencontainers.image.created": LEGACY_CREATED}
    if not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected.items()):
        raise RestoreError("fixed image OCI source identity does not match")

    before = {CURRENT_TAG: snapshot(client, CURRENT_TAG), "latest": snapshot(client, "latest", missing=True)}
    if before[CURRENT_TAG]["digest"] != CURRENT_DIGEST:
        raise RestoreError("current formal Auth reference does not match its fixed digest")
    previous = client.manifest(LEGACY_TAG, allow_missing=True, head=True)
    prior_digest = header(previous, "docker-content-digest")
    if previous.status != 404 and (previous.status != 200 or prior_digest != LEGACY_DIGEST):
        raise RestoreError("legacy tag already refers to different content")
    attempted = previous.status == 404
    write_status = 0
    uncertain = False
    if attempted:
        try:
            write_response = client.put_manifest(source.body)
            write_status = write_response.status
            uncertain = write_response.status != 201 or header(write_response, "docker-content-digest") != LEGACY_DIGEST
        except NETWORK_ERRORS + (RestoreError,):
            uncertain = True
    observed = client.manifest(LEGACY_TAG, allow_missing=True)
    verify_manifest(observed, LEGACY_DIGEST)
    confirmed = client.manifest(LEGACY_TAG, head=True)
    if confirmed.status != 200 or header(confirmed, "docker-content-digest") != LEGACY_DIGEST:
        raise RestoreError("legacy tag read-back did not confirm the fixed digest")
    after = {CURRENT_TAG: snapshot(client, CURRENT_TAG), "latest": snapshot(client, "latest", missing=True)}
    if before != after:
        raise RestoreError("protected references changed during tag restoration")
    return {"sourceSha256": sha256(source.body), "platformSha256": PLATFORM_DIGEST,
            "configSha256": config_digest, "sourceIdentityVerified": True,
            "legacyBeforeStatus": previous.status, "legacyAfterStatus": confirmed.status,
            "legacyAfterDigest": LEGACY_DIGEST, "writeAttempted": attempted,
            "writeResponseStatus": write_status, "writeResponseUncertain": uncertain,
            "singleWriteAtMost": True, "rebuilt": False,
            "currentReferenceUnchanged": True, "latestReferenceUnchanged": True,
            "currentBeforeStatus": before[CURRENT_TAG]["status"], "currentAfterStatus": after[CURRENT_TAG]["status"],
            "currentBeforeDigest": before[CURRENT_TAG]["digest"], "currentAfterDigest": after[CURRENT_TAG]["digest"],
            "latestBeforeStatus": before["latest"]["status"], "latestAfterStatus": after["latest"]["status"],
            "latestBeforeDigest": before["latest"]["digest"], "latestAfterDigest": after["latest"]["digest"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    username = os.environ.get("ALIYUN_REGISTRY_USERNAME", "")
    password = os.environ.get("ALIYUN_REGISTRY_PASSWORD", "")
    if not username or not password:
        raise RestoreError("the existing ACR credentials are required")
    client = RegistryClient(username, password)
    client.authenticate()
    proof = restore(client)
    args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print("fixed legacy Auth tag verified; protected references unchanged")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RestoreError as error:
        print("legacy Auth tag restoration stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("legacy Auth tag restoration stopped: unexpected verification failure", file=sys.stderr)
        sys.exit(1)
