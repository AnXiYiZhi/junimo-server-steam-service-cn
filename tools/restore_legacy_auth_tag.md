# Restore the legacy Auth ACR tag

The controlled `Restore fixed legacy Auth ACR tag` workflow restores the missing
ACR tag `anxi-panel/junimo-steam-service-cn:1.5.0-anxi.2` from the original OCI
index that remains stored in the same repository. The image digest stays
`sha256:99420ab30c09da019c425defd4d01796403ac03898ed261b9ee2a976f4bc6518`.

The source index includes the original linux/amd64 platform manifest
`sha256:34737f8b28e630a1d2994032bb158e577eb26bb5ba91683eae80770168db6da7`.
Its config must identify version `1.5.0-anxi.2`, exact OCI revision
`a6cee498f91b`, and build time `2026-07-05T18:48:08Z` before the tag can be
restored. The workflow independently checks that the original Git tag resolves
to full source commit `a6cee498f91b318cfcacf035b05b0644bd16829a`. The safe label
fixture was read from the actual public config blob
`sha256:5a9f895f6e8cc2a5e8d9d03d34cb69ca94ffbc04ad149578e89c82c911ca500a`.

`tools/restore_legacy_auth_tag.py` checks the index, platform and config bytes
against their digests. It records the current `1.5.0-preview.140-anxi.1` and
`latest` status/digest before and after the operation and requires them to stay
identical. A missing legacy tag permits one PUT of the original index bytes.
An existing matching tag is an idempotent success; different content stops the
operation. An uncertain PUT result is resolved by reads of the same tag, with
no second PUT.

The workflow runs only through `workflow_dispatch` on `master`, uses the
existing `ALIYUN_REGISTRY_USERNAME` and `ALIYUN_REGISTRY_PASSWORD` secrets, and
has read-only repository permissions. Credentials and tokens remain in memory.
Registry error bodies and signed object-storage URLs are not logged or saved.
The config blob redirect is limited to the known Hangzhou ACR object-storage
host and receives no registry Authorization header.

After review and push to `master`, an authorized maintainer runs:

```sh
gh workflow run restore-legacy-auth-tag.yml \
  --repo AnXiYiZhi/junimo-server-steam-service-cn --ref master
```

The artifact `legacy-auth-acr-tag-restoration-<run-id>` contains only status,
boolean and digest evidence. Inspect that artifact and the completed run, then
verify the restored tag anonymously against the fixed index digest before
resuming the Panel candidate. This operation does not build an image or create
a Git tag or GitHub Release; the current Auth publication remains unchanged.

Offline validation:

```sh
python3 -m unittest discover -s tests/workflows -p test_restore_legacy_auth_tag.py
```

Implementation status: prepared for maintainer review; the helper has not been
dispatched and no registry mutation has been performed during preparation.
