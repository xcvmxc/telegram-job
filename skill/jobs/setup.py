#!/usr/bin/env python3
"""Setup helper for the Telegram job scanner.

Called by the /tgjobs-setup wizard so each step is deterministic and testable.

Subcommands:

    check                    report what's installed / configured (JSON)
    save-creds --api-id ID --api-hash HASH
                             write ~/.claude/telegram/credentials.env
    init --folder PATH       write config.json and scaffold the two editable
                             files into PATH (never clobbers existing edits)
    status                   print current config + DB counts (JSON)

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

import config

TG_DIR = pathlib.Path.home() / ".claude" / "telegram"
CREDS_FILE = TG_DIR / "credentials.env"
SESSION_FILE = TG_DIR / "jobscan.session"
# Templates ship next to this script (installed at ~/.claude/jobs/templates/).
TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent / "templates"


def cmd_check(_args: argparse.Namespace) -> int:
    result = {
        "uv_installed": shutil.which("uv") is not None,
        "config_exists": config.CONFIG_PATH.exists(),
        "creds_exist": CREDS_FILE.exists(),
        "session_exists": SESSION_FILE.exists(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_save_creds(args: argparse.Namespace) -> int:
    api_id = (args.api_id or "").strip()
    api_hash = (args.api_hash or "").strip()
    if not api_id.isdigit():
        print(f"TG_API_ID must be a number, got: {api_id!r}", file=sys.stderr)
        return 2
    if len(api_hash) < 16:
        print("TG_API_HASH looks too short — copy the full hash from my.telegram.org.",
              file=sys.stderr)
        return 2
    TG_DIR.mkdir(parents=True, exist_ok=True)
    CREDS_FILE.write_text(
        f"TG_API_ID={api_id}\nTG_API_HASH={api_hash}\n", encoding="utf-8"
    )
    try:
        CREDS_FILE.chmod(0o600)
    except OSError:
        pass
    print(json.dumps({"creds_written": str(CREDS_FILE)}, ensure_ascii=False, indent=2))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    folder = pathlib.Path(args.folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)

    config.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.CONFIG_PATH.write_text(
        json.dumps({"folder": str(folder)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    scaffolded = []
    skipped = []
    for filename in (config.CRITERIA_FILENAME, config.SOURCES_FILENAME):
        dest = folder / filename
        if dest.exists():
            skipped.append(str(dest))  # never overwrite the user's edits
            continue
        src = TEMPLATES_DIR / filename
        if not src.exists():
            print(f"template missing: {src}", file=sys.stderr)
            return 2
        shutil.copyfile(src, dest)
        scaffolded.append(str(dest))

    print(json.dumps({
        "config_written": str(config.CONFIG_PATH),
        "folder": str(folder),
        "scaffolded": scaffolded,
        "already_existed": skipped,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    import db
    data = config.load()
    conn = db.connect()
    counts = {
        "channels": conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0],
        "messages_pending": conn.execute(
            "SELECT COUNT(*) FROM messages WHERE is_processed = 0").fetchone()[0],
        "matches_total": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
    }
    print(json.dumps({
        "folder": str(data["folder"]),
        "sources_file": str(config.sources_file()),
        "criteria_file": str(config.criteria_file()),
        "creds_exist": CREDS_FILE.exists(),
        "session_exists": SESSION_FILE.exists(),
        "db": counts,
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Setup helper for the Telegram job scanner.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Report install/config state.")

    p_creds = sub.add_parser("save-creds", help="Write Telegram API credentials.")
    p_creds.add_argument("--api-id", required=True)
    p_creds.add_argument("--api-hash", required=True)

    p_init = sub.add_parser("init", help="Write config.json and scaffold editable files.")
    p_init.add_argument("--folder", required=True)

    sub.add_parser("status", help="Print current config + DB counts.")

    args = parser.parse_args()
    handler = {
        "check": cmd_check,
        "save-creds": cmd_save_creds,
        "init": cmd_init,
        "status": cmd_status,
    }[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
