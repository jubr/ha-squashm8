#!/usr/bin/env python3
"""Bump Home Assistant integration version in manifest.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    """Parse a strict semver string (major.minor.patch)."""
    match = SEMVER_PATTERN.match(value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Path to manifest.json")
    parser.add_argument(
        "--bump",
        choices=("patch", "minor"),
        required=True,
        help="Version part to bump",
    )
    parser.add_argument(
        "--start-version",
        default="0.0.1",
        help="Initial semver used if version is missing/invalid",
    )
    args = parser.parse_args()

    start_version = _parse_semver(args.start_version)
    if start_version is None:
        raise ValueError(f"Invalid --start-version: {args.start_version}")

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    current_raw = manifest.get("version")
    current = _parse_semver(current_raw) if isinstance(current_raw, str) else None
    major, minor, patch = current if current is not None else start_version

    if current is not None:
        if args.bump == "minor":
            minor += 1
            patch = 0
        else:
            patch += 1

    new_version = f"{major}.{minor}.{patch}"
    manifest["version"] = new_version
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(new_version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
