#!/usr/bin/env python3
"""Strict tag parsing and deterministic metadata for upstream sync workflows."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PREVIEW_RE = re.compile(r"^preview-(\d+)\.(\d+)\.(\d+)\.(\d+)$")
STABLE_RE = re.compile(r"^sdvd-server-v(\d+)\.(\d+)\.(\d+)$")
FORK_RE = re.compile(
    r"^sdvd-server-v(\d+)\.(\d+)\.(\d+)(?:-preview\.(\d+))?-anxi\.(\d+)$"
)


@dataclass(frozen=True)
class UpstreamTag:
    name: str
    channel: str
    version: tuple[int, ...]

    @property
    def branch(self) -> str:
        normalized = re.sub(r"[^a-z0-9._-]+", "-", self.name.lower()).strip("-")
        return f"sync/upstream-{normalized}"

    @property
    def recommended_fork_tag(self) -> str:
        if self.channel == "preview":
            major, minor, patch, sequence = self.version
            return f"sdvd-server-v{major}.{minor}.{patch}-preview.{sequence}-anxi.1"
        major, minor, patch = self.version
        return f"sdvd-server-v{major}.{minor}.{patch}-anxi.1"


def parse_upstream_tag(value: str) -> UpstreamTag:
    if match := PREVIEW_RE.fullmatch(value):
        return UpstreamTag(value, "preview", tuple(map(int, match.groups())))
    if match := STABLE_RE.fullmatch(value):
        return UpstreamTag(value, "stable", tuple(map(int, match.groups())))
    raise ValueError(
        "tag must match preview-X.Y.Z.N or sdvd-server-vX.Y.Z exactly"
    )


def parse_fork_tag(value: str) -> dict[str, str]:
    match = FORK_RE.fullmatch(value)
    if not match:
        raise ValueError(
            "release tag must match sdvd-server-vX.Y.Z[-preview.N]-anxi.N exactly"
        )
    major, minor, patch, preview, anxi = match.groups()
    if preview is None:
        version = f"{major}.{minor}.{patch}-anxi.{anxi}"
        upstream_tag = f"sdvd-server-v{major}.{minor}.{patch}"
    else:
        version = f"{major}.{minor}.{patch}-preview.{preview}-anxi.{anxi}"
        upstream_tag = f"preview-{major}.{minor}.{patch}.{preview}"
    return {"version": version, "upstream_tag": upstream_tag}


def discover(tags: Iterable[str], requested: str = "") -> list[UpstreamTag]:
    parsed: list[UpstreamTag] = []
    for raw in tags:
        value = raw.strip()
        if not value:
            continue
        try:
            parsed.append(parse_upstream_tag(value))
        except ValueError:
            continue
    by_name = {tag.name: tag for tag in parsed}
    if requested:
        requested_tag = parse_upstream_tag(requested)
        if requested_tag.name not in by_name:
            raise ValueError(f"upstream tag {requested!r} does not exist")
        return [requested_tag]
    result: list[UpstreamTag] = []
    for channel in ("stable", "preview"):
        candidates = [tag for tag in by_name.values() if tag.channel == channel]
        if candidates:
            result.append(max(candidates, key=lambda tag: tag.version))
    return result


def overlap_files(fork_files: Iterable[str], upstream_files: Iterable[str]) -> list[str]:
    return sorted(set(fork_files) & set(upstream_files))


def pr_action(existing_pr_number: str) -> str:
    return "update" if existing_pr_number.strip() else "create"


def write_outputs(path: str, values: dict[str, str]) -> None:
    with Path(path).open("a", encoding="utf-8", newline="\n") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover_parser = subparsers.add_parser("discover")
    discover_parser.add_argument("--tags-file", required=True)
    discover_parser.add_argument("--requested", default="")
    discover_parser.add_argument("--github-output", required=True)

    metadata_parser = subparsers.add_parser("metadata")
    metadata_parser.add_argument("--tag", required=True)
    metadata_parser.add_argument("--github-output", required=True)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--tag", required=True)
    release_parser.add_argument("--github-output", required=True)

    args = parser.parse_args()
    try:
        if args.command == "discover":
            tags = Path(args.tags_file).read_text(encoding="utf-8").splitlines()
            targets = discover(tags, args.requested.strip())
            write_outputs(
                args.github_output,
                {"targets": json.dumps([{"tag": tag.name} for tag in targets])},
            )
        elif args.command == "metadata":
            tag = parse_upstream_tag(args.tag)
            write_outputs(
                args.github_output,
                {
                    "channel": tag.channel,
                    "branch": tag.branch,
                    "recommended_fork_tag": tag.recommended_fork_tag,
                },
            )
        else:
            values = parse_fork_tag(args.tag)
            values["created"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            write_outputs(args.github_output, values)
    except ValueError as error:
        print(f"::error::{error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
