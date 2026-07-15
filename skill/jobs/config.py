#!/usr/bin/env python3
"""Config for the Telegram job scanner.

Single source of truth: ~/.claude/jobs/config.json

    { "folder": "/absolute/path/to/job-hunt" }

`folder` is the one thing the user chooses. It holds the two files they edit
and receives the output:

    <folder>/Search Criteria.md    what to look for (read by the classifier)
    <folder>/Telegram Sources.md   channels/groups to scan
    <folder>/matches+<stamp>.md    output written by `emit-files`

For testing / power users, JOBS_CONFIG overrides the config path.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

CONFIG_PATH = pathlib.Path(
    os.environ.get("JOBS_CONFIG") or (pathlib.Path.home() / ".claude" / "jobs" / "config.json")
)

SOURCES_FILENAME = "Telegram Sources.md"
CRITERIA_FILENAME = "Search Criteria.md"

_MISSING = (
    "Job scanner is not set up yet.\n"
    f"  No config at {CONFIG_PATH}.\n"
    "  Run /jobs-setup in Claude Code to configure it."
)


def load() -> dict:
    if not CONFIG_PATH.exists():
        print(_MISSING, file=sys.stderr)
        sys.exit(2)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Config at {CONFIG_PATH} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print(f"Config at {CONFIG_PATH} must be a JSON object. Run /jobs-setup.", file=sys.stderr)
        sys.exit(2)
    folder = (data.get("folder") or "").strip()
    if not folder:
        print(f"Config at {CONFIG_PATH} has no \"folder\". Run /jobs-setup.", file=sys.stderr)
        sys.exit(2)
    data["folder"] = pathlib.Path(folder).expanduser()
    return data


def folder() -> pathlib.Path:
    return load()["folder"]


def sources_file() -> pathlib.Path:
    return folder() / SOURCES_FILENAME


def criteria_file() -> pathlib.Path:
    return folder() / CRITERIA_FILENAME


def _main() -> int:
    """Tiny CLI so the /jobs command can resolve paths:

        python3 config.py folder
        python3 config.py sources-file
        python3 config.py criteria-file
    """
    key = sys.argv[1] if len(sys.argv) > 1 else "folder"
    resolver = {
        "folder": folder,
        "sources-file": sources_file,
        "criteria-file": criteria_file,
    }.get(key)
    if resolver is None:
        print(f"unknown key: {key}", file=sys.stderr)
        return 2
    print(resolver())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
