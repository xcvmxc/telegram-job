#!/usr/bin/env python3
"""Telegram channel scanner for the /jobs command — a dumb fetcher.

It logs in once (interactively) with a Telethon user session, then emits recent
messages from the requested channels as JSON. It does NOT decide what is a job
posting — that reasoning lives in ~/.claude/commands/jobs.md. This script only
fetches raw messages + any links it finds, and builds stable permalinks.

Run it through uv so Telethon is provided in an isolated env (no system installs):

    # one-time login (you type the SMS code; creates the session file)
    uv run --with telethon python ~/.claude/telegram/tg_scan.py login

    # list the channels your account is in (to grab refs / ids)
    uv run --with telethon python ~/.claude/telegram/tg_scan.py list

    # scan one or more channels, last 14 days, JSON to stdout
    uv run --with telethon python ~/.claude/telegram/tg_scan.py scan \
        --channel @somejobschannel --channel "t.me/+abcInviteHash" --days 14

Credentials are read from ~/.claude/telegram/credentials.env:
    TG_API_ID=1234567
    TG_API_HASH=0123456789abcdef0123456789abcdef
(or from the TG_API_ID / TG_API_HASH environment variables).
The session is stored at ~/.claude/telegram/jobscan.session.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys

BASE = pathlib.Path.home() / ".claude" / "telegram"
SESSION = str(BASE / "jobscan")
CREDS_FILE = BASE / "credentials.env"


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def load_creds() -> tuple[int, str]:
    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    if (not api_id or not api_hash) and CREDS_FILE.exists():
        for raw in CREDS_FILE.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key == "TG_API_ID" and not api_id:
                api_id = value
            elif key == "TG_API_HASH" and not api_hash:
                api_hash = value
    if not api_id or not api_hash:
        eprint(
            "Missing Telegram credentials.\n"
            f"  Put TG_API_ID and TG_API_HASH in {CREDS_FILE}\n"
            "  (get them from https://my.telegram.org -> API development tools),\n"
            "  or export them as environment variables."
        )
        sys.exit(2)
    try:
        return int(api_id), api_hash
    except ValueError:
        eprint(f"TG_API_ID must be an integer, got: {api_id!r}")
        sys.exit(2)


def make_client():
    # Imported lazily so `--help` works without Telethon present.
    from telethon.sync import TelegramClient

    api_id, api_hash = load_creds()
    return TelegramClient(SESSION, api_id, api_hash)


def normalize_ref(ref: str) -> object:
    """Turn a Job Sources URL/handle into something Telethon can resolve."""
    ref = ref.strip()
    for prefix in ("tg://", "https://", "http://"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    ref = ref.replace("t.me/", "").replace("telegram.me/", "")
    ref = ref.strip("/")
    # Numeric channel id, e.g. -1001234567890 (private channels referenced by id).
    if ref.lstrip("-").isdigit():
        return int(ref)
    # Invite links (t.me/+hash or t.me/joinchat/hash) — keep the full link form.
    if ref.startswith("+") or ref.startswith("joinchat/"):
        return "https://t.me/" + ref
    return ref


def marked_id(entity) -> int | None:
    """Bot-API style id (e.g. -1001234567890) — the canonical, resolvable form."""
    from telethon import utils

    try:
        return utils.get_peer_id(entity)
    except Exception:  # noqa: BLE001
        return getattr(entity, "id", None)


def to_marked(cid: int) -> int:
    """Accept a raw (unmarked) channel id and return its -100… form."""
    if cid > 0:
        return int(f"-100{cid}")
    return cid


def permalink(entity, msg_id: int) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"https://t.me/{username}/{msg_id}"
    # Private channel: web permalink uses the id with the -100 prefix stripped.
    mid = marked_id(entity)
    if mid is not None:
        short = str(mid)
        if short.startswith("-100"):
            short = short[4:]
        elif short.startswith("-"):
            short = short[1:]
        return f"https://t.me/c/{short}/{msg_id}"
    return ""


def extract_urls(message) -> list[str]:
    urls: list[str] = []
    text = message.message or ""
    for ent, val in (message.get_entities_text() or []):
        cls = type(ent).__name__
        if cls == "MessageEntityTextUrl" and getattr(ent, "url", None):
            urls.append(ent.url)
        elif cls == "MessageEntityUrl":
            urls.append(val)
    # Buttons (inline keyboards) often hold the real "Apply" link.
    markup = getattr(message, "reply_markup", None)
    if markup is not None:
        for row in getattr(markup, "rows", []) or []:
            for btn in getattr(row, "buttons", []) or []:
                burl = getattr(btn, "url", None)
                if burl:
                    urls.append(burl)
    # Dedup, keep order.
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def cmd_login(_args: argparse.Namespace) -> int:
    with make_client() as client:
        me = client.get_me()
        name = getattr(me, "username", None) or getattr(me, "first_name", "?")
        eprint(f"Logged in as @{name}. Session saved at {SESSION}.session")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    with make_client() as client:
        rows = []
        for dialog in client.iter_dialogs():
            if not (dialog.is_channel or dialog.is_group):
                continue
            ent = dialog.entity
            username = getattr(ent, "username", None)
            mid = marked_id(ent)
            # Ready-to-paste value for your `Telegram Sources.md` file. Public
            # channels get an @handle; private ones fall back to a numeric id.
            suggested_ref = f"@{username}" if username else (str(mid) if mid is not None else None)
            rows.append(
                {
                    "title": dialog.name,
                    "id": mid,
                    "username": username,
                    "is_private": username is None,
                    "suggested_ref": suggested_ref,
                }
            )
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
        print()
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    # --min-id (cursor) takes precedence: when set, --days is ignored and we
    # walk newest→oldest until we cross the cursor.
    min_id = int(getattr(args, "min_id", 0) or 0)
    cutoff = None
    if min_id == 0 and args.days is not None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)

    norm_refs = [(ref, normalize_ref(ref)) for ref in args.channel]

    results: list[dict] = []
    errors: list[dict] = []
    with make_client() as client:
        # Numeric/private ids only resolve if the session already knows the
        # channel. Warm the entity cache once and index it by marked id.
        cache: dict[int, object] = {}
        if any(isinstance(norm, int) for _, norm in norm_refs):
            for dialog in client.iter_dialogs():
                mid = marked_id(dialog.entity)
                if mid is not None:
                    cache[mid] = dialog.entity

        for ref, norm in norm_refs:
            try:
                if isinstance(norm, int):
                    entity = cache.get(norm) or cache.get(to_marked(norm))
                    if entity is None:
                        entity = client.get_entity(norm)
                else:
                    entity = client.get_entity(norm)
            except Exception as exc:  # noqa: BLE001 - report and continue
                errors.append({"channel": ref, "error": f"{type(exc).__name__}: {exc}"})
                continue
            if entity is None:
                errors.append({"channel": ref, "error": "not found in your dialogs — are you a member of this channel?"})
                continue
            count = 0
            iter_kwargs = {"limit": args.limit}
            if min_id > 0:
                iter_kwargs["min_id"] = min_id
                # Resume path: iterate OLDEST→newest so the per-scan limit
                # truncates the NEW end, not the old. Otherwise, when more than
                # `limit` messages accumulate above the cursor, the newest-first
                # default would return only the newest `limit` while the caller
                # advances the cursor to MAX(msg_id) — silently dropping the
                # older middle band forever. reverse=True keeps the cursor
                # advancing contiguously. Safe here because cutoff is None in
                # the min_id path (the --days path below still needs
                # newest-first for its `msg.date < cutoff` early break).
                iter_kwargs["reverse"] = True
            for msg in client.iter_messages(entity, **iter_kwargs):
                if cutoff is not None and msg.date and msg.date < cutoff:
                    break
                text = msg.message or ""
                # Extract links BEFORE the skip guard: a caption-less media post
                # can still carry the real "Apply" link in an inline button.
                urls = extract_urls(msg)
                if not text.strip() and not urls:
                    continue  # skip only pure media / service messages (no links)
                results.append(
                    {
                        "channel_ref": ref,
                        "channel_title": getattr(entity, "title", None),
                        "channel_id": getattr(entity, "id", None),
                        "channel_username": getattr(entity, "username", None),
                        "msg_id": msg.id,
                        "date": msg.date.isoformat() if msg.date else None,
                        "permalink": permalink(entity, msg.id),
                        "text": text,
                        "urls": urls,
                    }
                )
                count += 1
            eprint(f"  {ref}: {count} messages")

    json.dump(
        {"messages": results, "errors": errors},
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    print()
    return 1 if errors and not results else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram channel scanner for /jobs.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Interactive one-time login; creates the session file.")
    sub.add_parser("list", help="List channels/groups your account is in (JSON).")

    scan = sub.add_parser("scan", help="Fetch recent messages from channels (JSON).")
    scan.add_argument(
        "--channel",
        action="append",
        required=True,
        metavar="REF",
        help="@username, t.me/username, t.me/+invite, t.me/c/<id>, or numeric id. Repeatable.",
    )
    scan.add_argument("--days", type=int, default=14, help="Only messages newer than N days (default 14). Ignored if --min-id is set.")
    scan.add_argument("--min-id", type=int, default=0, help="Only messages with msg_id > MIN_ID (cursor-based resume; overrides --days).")
    scan.add_argument("--limit", type=int, default=200, help="Max messages per channel (default 200).")

    args = parser.parse_args()
    handler = {"login": cmd_login, "list": cmd_list, "scan": cmd_scan}[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
