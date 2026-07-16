#!/usr/bin/env python3
"""Update check for the Telegram job scanner.

`check` compares the installed VERSION against the latest on the repo's main
branch — at most once per day, and never blocks the pipeline. The /tg-intent
command runs it at the very end and, if a newer version exists, offers an update.

Applying an update is done by re-running the installer in --update mode
(curl ... | bash -s -- --update), which refreshes the shared backend AND every
agent the skill is installed in — all at once — while keeping all state.

Stdlib only. Works before setup (only needs $TGJOBS_HOME, not config.json).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request

import config

HOME = config.TGJOBS_HOME
VERSION_FILE = HOME / "VERSION"
STAMP_FILE = HOME / ".last_update_check"
REMOTE_VERSION_URL = "https://raw.githubusercontent.com/xcvmxc/telegram-intent/main/VERSION"
TIMEOUT = 3


def _read_local() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _parse(v: str) -> tuple:
    out = []
    for p in (v or "").strip().split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out) or (0,)


def _newer(remote: str, local: str) -> bool:
    r, l = _parse(remote), _parse(local)
    n = max(len(r), len(l))
    return r + (0,) * (n - len(r)) > l + (0,) * (n - len(l))


def _today() -> str:
    return dt.date.today().isoformat()


def cmd_check(force: bool) -> dict:
    local = _read_local()
    # Throttle: at most one network check per day, unless --force.
    if not force:
        try:
            if STAMP_FILE.read_text(encoding="utf-8").strip() == _today():
                return {"update_available": False, "local": local, "throttled": True}
        except OSError:
            pass
    remote = None
    try:
        with urllib.request.urlopen(REMOTE_VERSION_URL, timeout=TIMEOUT) as r:
            remote = r.read().decode("utf-8").strip()
    except Exception:  # noqa: BLE001 - any failure = no update offered, never break
        remote = None
    try:
        STAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
        STAMP_FILE.write_text(_today(), encoding="utf-8")
    except OSError:
        pass
    if not remote:
        return {"update_available": False, "local": local, "remote": None}
    return {
        "update_available": _newer(remote, local),
        "local": local,
        "remote": remote,
    }


def main() -> int:
    args = sys.argv[1:]
    force = "--force" in args
    cmd = next((a for a in args if not a.startswith("-")), "check")
    if cmd != "check":
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    print(json.dumps(cmd_check(force), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
