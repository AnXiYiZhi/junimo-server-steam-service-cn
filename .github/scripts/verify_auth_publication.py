#!/usr/bin/env python3
"""Verify a previously built Auth payload before registry-only recovery."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess

from upstream_release import parse_fork_tag, pinned_upstream_revision


def verify(source: Path, tag: str, image: dict) -> dict:
    metadata = parse_fork_tag(tag)
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    upstream = pinned_upstream_revision(
        str(source / "tools/steam-service/upstream-release.json"), metadata["upstream_tag"]
    )
    subprocess.run(
        ["git", "-C", str(source), "merge-base", "--is-ancestor", upstream, revision],
        check=True,
    )
    archive = subprocess.check_output(
        ["git", "-C", str(source), "archive", "HEAD", "tools/steam-service",
         "Directory.Build.props", "CodeStyle.props", ".editorconfig"]
    )
    tree = hashlib.sha256(archive).hexdigest()
    labels = image["Config"]["Labels"]
    expected = {
        "org.opencontainers.image.version": metadata["version"],
        "org.opencontainers.image.revision": revision,
        "com.anxi-panel.upstream-revision": upstream,
        "com.anxi-panel.source-tree-sha256": tree,
    }
    if any(labels.get(key) != value for key, value in expected.items()):
        raise ValueError("previously built Auth image does not match the reviewed release source")
    created = labels["org.opencontainers.image.created"]
    offset = datetime.fromisoformat(created.replace("Z", "+00:00")).utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("image build date must be UTC")
    return {"version": metadata["version"], "sourceRevision": revision,
            "upstreamRevision": upstream, "sourceTreeSHA256": tree, "buildDate": created}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--inspect", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image = json.loads(args.inspect.read_text(encoding="utf-8"))[0]
    result = verify(args.source, args.tag, image)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
