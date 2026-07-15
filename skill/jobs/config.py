#!/usr/bin/env python3
"""Config for the Telegram job scanner.

Single source of truth: ~/.claude/jobs/config.json

    { "folder": "/absolute/path/to/job-hunt" }

`folder` is the one thing the user chooses. It holds the two files they edit
and receives the output:

    <folder>/Search Criteria.md    what to look for (read by the classifier)
    <folder>/Telegram Sources.md   channels/groups to scan
    <folder>/вакансии+<stamp>.md    output written by `emit-files`

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
    "Сканер вакансий ещё не настроен.\n"
    f"  Нет конфига в {CONFIG_PATH}.\n"
    "  Запустите /tgjobs-setup в Claude Code, чтобы настроить."
)


def load() -> dict:
    if not CONFIG_PATH.exists():
        print(_MISSING, file=sys.stderr)
        sys.exit(2)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Конфиг {CONFIG_PATH} — некорректный JSON: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print(f"Конфиг {CONFIG_PATH} должен быть JSON-объектом. Запустите /tgjobs-setup.", file=sys.stderr)
        sys.exit(2)
    folder = (data.get("folder") or "").strip()
    if not folder:
        print(f"В конфиге {CONFIG_PATH} нет \"folder\". Запустите /tgjobs-setup.", file=sys.stderr)
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
    """Tiny CLI so the /tgjobs command can resolve paths:

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
