#!/usr/bin/env python3
"""Config for the Telegram job scanner.

Everything lives under TGJOBS_HOME (default ~/.tgjobs), so the product is
agent-neutral — Claude Code, Codex, Gemini and Cursor all point at the same
backend and share one state DB.

Single source of truth: $TGJOBS_HOME/jobs/config.json

    { "folder": "/absolute/path/to/job-hunt", "lang": "en" }

`folder` holds the two files the user edits and receives the output:

    <folder>/Search Criteria.md    what to look for (read by the classifier)
    <folder>/Telegram Sources.md   channels/groups to scan
    <folder>/matches+<stamp>.md    output written by `emit-files`

`lang` (en|ru, default en) only affects the wording of the emitted output file.

Overrides for testing/power users: TGJOBS_HOME, JOBS_CONFIG.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

TGJOBS_HOME = pathlib.Path(
    os.environ.get("TGJOBS_HOME") or (pathlib.Path.home() / ".tgjobs")
)

CONFIG_PATH = pathlib.Path(
    os.environ.get("JOBS_CONFIG") or (TGJOBS_HOME / "jobs" / "config.json")
)

SOURCES_FILENAME = "Telegram Sources.md"
CRITERIA_FILENAME = "Search Criteria.md"
DEFAULT_LANG = "en"

_MISSING = (
    "Job scanner is not set up yet.\n"
    f"  No config at {CONFIG_PATH}.\n"
    "  Run /tg-intent-setup to configure it."
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
        print(f"Config at {CONFIG_PATH} must be a JSON object. Run /tg-intent-setup.", file=sys.stderr)
        sys.exit(2)
    folder = str(data.get("folder") or "").strip()
    if not folder:
        print(f"Config at {CONFIG_PATH} has no \"folder\". Run /tg-intent-setup.", file=sys.stderr)
        sys.exit(2)
    data["folder"] = pathlib.Path(folder).expanduser()
    lang = str(data.get("lang") or DEFAULT_LANG).strip().lower()
    data["lang"] = lang if lang in ("en", "ru") else DEFAULT_LANG
    # Export-time dedup window (days) for same company+position under a
    # different link. Default 3; 0 disables. Power users can set it in config.
    try:
        data["export_dedup_days"] = max(0, int(data.get("export_dedup_days", 2)))
    except (TypeError, ValueError):
        data["export_dedup_days"] = 2
    # How many days of messages + matched jobs to keep; older rows are pruned at
    # the start of each pull (channel cursors are never pruned). Kept at least as
    # long as the dedup window so pruning never breaks repost suppression.
    try:
        data["retention_days"] = max(1, int(data.get("retention_days", 2)))
    except (TypeError, ValueError):
        data["retention_days"] = 2
    data["retention_days"] = max(data["retention_days"], data["export_dedup_days"])
    return data


def folder() -> pathlib.Path:
    return load()["folder"]


def lang() -> str:
    return load()["lang"]


def sources_file() -> pathlib.Path:
    return folder() / SOURCES_FILENAME


def criteria_file() -> pathlib.Path:
    return folder() / CRITERIA_FILENAME


def _main() -> int:
    """Tiny CLI so the /tg-intent command can resolve paths / settings:

        python3 config.py folder
        python3 config.py sources-file
        python3 config.py criteria-file
        python3 config.py lang
    """
    key = sys.argv[1] if len(sys.argv) > 1 else "folder"
    resolver = {
        "folder": folder,
        "sources-file": sources_file,
        "criteria-file": criteria_file,
        "lang": lang,
    }.get(key)
    if resolver is None:
        print(f"unknown key: {key}", file=sys.stderr)
        return 2
    print(resolver())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
