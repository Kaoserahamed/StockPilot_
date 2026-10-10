#!/usr/bin/env python
"""Generate the backend lockfiles.

``requirements.txt`` pins only the direct runtime dependencies and
``requirements-dev.txt`` pins the direct test/lint tooling. This script resolves
the full dependency closure of each with pip's dry-run report and writes exact
pins for every transitive package, so a fresh clone installs a byte-for-byte
reproducible tree.

Usage (from the ``backend`` directory)::

    python scripts/generate_lockfile.py          # requirements.lock
    python scripts/generate_lockfile.py --dev    # requirements-dev.lock

Verify a clean install with::

    python -m venv /tmp/verify && /tmp/verify/bin/pip install -r requirements.lock

``pip-compile`` from pip-tools (pinned in requirements-dev.txt) is the
conventional alternative::

    pip-compile --output-file=requirements.lock requirements.txt

The output is intentionally free of timestamps so re-running it produces no diff
unless a dependency actually changed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
RUNTIME_REQUIREMENTS = BACKEND_DIR / "requirements.txt"
DEV_REQUIREMENTS = BACKEND_DIR / "requirements-dev.txt"

RUNTIME_LOCKFILE = BACKEND_DIR / "requirements.lock"
DEV_LOCKFILE = BACKEND_DIR / "requirements-dev.lock"

RUNTIME_HEADER = """\
# =============================================================================
# StockPilot backend - GENERATED LOCKFILE. DO NOT EDIT BY HAND.
#
# Contains the exact, fully resolved dependency closure of requirements.txt
# (direct + transitive), for reproducible installs:
#
#     pip install -r requirements.lock
#
# Regenerate after changing requirements.txt:
#
#     cd backend && python scripts/generate_lockfile.py
#
# `pip-compile` (pip-tools, pinned in requirements-dev.txt) is an equivalent
# alternative. Development-only tooling is deliberately excluded; it lives in
# requirements-dev.txt / requirements-dev.lock.
# =============================================================================
"""

DEV_HEADER = """\
# =============================================================================
# StockPilot backend - GENERATED LOCKFILE. DO NOT EDIT BY HAND.
#
# Contains the exact, fully resolved dependency closure of requirements.txt PLUS
# requirements-dev.txt (pytest, ruff, mypy, pip-audit, pre-commit, pip-tools and
# every transitive dependency), so a fresh clone installs the same test and lint
# environment everywhere:
#
#     pip install -r requirements-dev.lock
#
# Regenerate after changing either manifest:
#
#     cd backend && python scripts/generate_lockfile.py --dev
#
# `pip-compile` (pip-tools, pinned in requirements-dev.txt) is an equivalent
# alternative.
# =============================================================================
"""


def resolve_pins(manifests: Sequence[Path]) -> list[str]:
    """Ask pip to resolve ``manifests`` and return sorted ``name==version`` pins."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        report_path = Path(tmp_dir) / "pip-report.json"
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--quiet",
            "--report",
            str(report_path),
        ]
        for manifest in manifests:
            command += ["-r", str(manifest)]
        # The command is a fixed list built here - no shell, no untrusted input.
        subprocess.run(command, check=True, cwd=BACKEND_DIR)
        report = json.loads(report_path.read_text(encoding="utf-8"))

    pins: set[str] = set()
    for entry in report.get("install", []):
        metadata = entry.get("metadata", {})
        name = metadata.get("name")
        version = metadata.get("version")
        if name and version:
            pins.add(f"{name}=={version}")

    if not pins:
        raise SystemExit("pip resolved no packages - refusing to write an empty lockfile")

    return sorted(pins, key=str.lower)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dev",
        action="store_true",
        help="also lock the development tooling closure (requirements-dev.lock)",
    )
    args = parser.parse_args(argv)

    manifests: Sequence[Path]
    if args.dev:
        manifests = (RUNTIME_REQUIREMENTS, DEV_REQUIREMENTS)
        target, header = DEV_LOCKFILE, DEV_HEADER
    else:
        manifests = (RUNTIME_REQUIREMENTS,)
        target, header = RUNTIME_LOCKFILE, RUNTIME_HEADER

    pins = resolve_pins(manifests)
    body = "\n".join(pins)
    # newline="\n" keeps the generated file LF-only on every platform, so a
    # Windows checkout produces the same bytes as CI and a Linux contributor.
    target.write_text(f"{header}\n{body}\n", encoding="utf-8", newline="\n")
    print(f"Wrote {target} ({len(pins)} pinned packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
