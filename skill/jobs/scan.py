#!/usr/bin/env python3
"""Telegram job scanner.

Pipeline (subcommands driven by the /tg-intent command in whichever agent):

    pull                 fetch new TG messages using per-channel cursors, store
                         any message that has URLs, print a JSON summary
    unclassified         dump pending messages as JSON so the classifier can
                         decide is_job / is_match against the user's criteria
    save-classifications --json '...'   ingest the classifier's verdicts; store
                                        MATCHING vacancies under the intent(s)
                                        they fit (dedup by link+intent), mark
                                        every message processed
    emit-files [--since ISO]            write ONE file per intent to the user's
                                        folder (only this run's jobs)

Search Criteria.md can declare several INTENTS — independent searches, each with
its own "look for / exclude / notes" and its own export file. An intent is a
`## Intent: <name>` header (Russian `## Интент: <name>` also works). A file with
no such headers is a single default search (output: matches+<stamp>.md).

Everything user-specific lives in the folder from config.json:
    <folder>/Search Criteria.md    what to look for, one or more intents
    <folder>/Telegram Sources.md   channels/groups to scan
    <folder>/<intent>+<stamp>.md   output, one file per intent (default intent
                                   keeps the localized matches+/вакансии+ name)

Stdlib only. Shells out to $TGJOBS_HOME/telegram/tg_scan.py (Telethon via uv).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sqlite3
import subprocess
import sys
import unicodedata

import config
import db

TG_SCAN = config.TGJOBS_HOME / "telegram" / "tg_scan.py"

# First scan of a channel (no cursor yet): last N days. Keeps the initial
# import small so the classifier isn't flooded on day one.
FIRST_SCAN_DAYS = 3

# Max messages per channel per scan. The cursor keeps later runs small; this
# caps the very first import.
CHANNEL_MSG_LIMIT = 500


# --- Sources file --------------------------------------------------------

def load_sources() -> list[str]:
    """Read `<folder>/Telegram Sources.md`.

    One channel/group reference per line, optionally written as a Markdown
    bullet ("- @channel", "* @channel"). Lines starting with '#' are comments,
    blank lines are ignored. Everything else is a source ref: @username,
    t.me/username, t.me/+invite, or a numeric -100… id.
    """
    path = config.sources_file()
    if not path.exists():
        return []
    refs: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        # Strip a leading bullet marker ("- @x") — but not a numeric id
        # ("-100…"), where the dash is followed by a digit, not whitespace.
        if line[:1] in "-*+•" and line[1:2] in (" ", "\t"):
            line = line[2:].strip()
        if not line or line.startswith("#"):
            continue
        if line not in seen:
            seen.add(line)
            refs.append(line)
    return refs


# --- intents -------------------------------------------------------------

# A declared intent is a header line `## Intent: <name>` (or Russian
# `## Интент: <name>`), case-insensitive, up to 3 leading spaces of Markdown
# indentation. The name after the colon becomes the intent's canonical label.
_INTENT_HEADER = re.compile(
    r"^\s{0,3}#{2,3}\s*(?:intent|интент)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)


def _canon_intent(name: str) -> str:
    """Comparison key for an intent name: NFC-normalized, casefolded, whitespace
    collapsed. Used to reconcile classifier output to declared names and to key
    the per-run file-collision set. The default intent is the empty string."""
    return " ".join(unicodedata.normalize("NFC", name or "").casefold().split())


def load_intents() -> list[str]:
    """Parse the intents declared in `<folder>/Search Criteria.md`.

    Returns the canonical display names (NFC-normalized, stripped) in file
    order, de-duplicated case-insensitively. Names that are empty/whitespace
    only after stripping are skipped. A file with no `## Intent:` headers
    returns [] — the whole file is then one default search (intent '')."""
    path = config.criteria_file()
    if not path.exists():
        return []
    names: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = _INTENT_HEADER.match(raw)
        if not m:
            continue
        name = unicodedata.normalize("NFC", m.group(1)).strip()
        if not name:
            continue
        key = _canon_intent(name)
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


# --- intent → filename ---------------------------------------------------

# Path-unsafe on common filesystems; '+' too (it separates <intent>+<stamp>).
_UNSAFE_FILENAME = re.compile(r'[\\/:\*\?"<>\|\+\x00-\x1f]')


def _sanitize_filename_base(name: str, fallback_index: int) -> str:
    """Turn a canonical intent name into a safe, readable filename base:
    unsafe chars → space, whitespace collapsed, no leading dot/plus (avoids
    hidden dotfiles), capped at 60 Unicode codepoints. Falls back to
    `intent-<n>` when nothing printable survives."""
    cleaned = _UNSAFE_FILENAME.sub(" ", name)
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.lstrip(".+ ").strip()
    if len(cleaned) > 60:
        cleaned = cleaned[:60].strip()
    if not cleaned or set(cleaned) <= {"."}:
        cleaned = f"intent-{fallback_index}"
    return cleaned


def _resolve_out_path(
    out_dir: pathlib.Path,
    base: str,
    stamp: str,
    used_norm: set,
    reserved: set,
) -> pathlib.Path:
    """Pick a non-clashing `<base>+<stamp>.md` path. Bumps `base (1)`, `base (2)`
    … when the NFC+casefold key is already taken this run, is reserved, or the
    file already exists on disk (guards case/normalization-insensitive
    filesystems like APFS and same-second reruns)."""
    n = 0
    while True:
        cand = base if n == 0 else f"{base} ({n})"
        key = _canon_intent(cand)
        path = out_dir / f"{cand}+{stamp}.md"
        if key not in used_norm and key not in reserved and not path.exists():
            used_norm.add(key)
            return path
        n += 1


# --- prune ---------------------------------------------------------------

def _prune(conn: sqlite3.Connection, days: int) -> None:
    """Delete stored messages and matched jobs older than `days` (by post date,
    falling back to fetch/extract time). Channel cursors are kept, so resume
    still works — only the accumulated history is trimmed."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    # Never prune messages that haven't been classified yet (a re-run of pull
    # before the classify step must not silently drop pending inputs).
    conn.execute("DELETE FROM messages WHERE is_processed = 1 AND COALESCE(msg_date, fetched_at) < ?", (cutoff,))
    # Prune jobs by extracted_at — the same key the export dedup queries — so a
    # just-extracted match from an older post survives its dedup window.
    conn.execute("DELETE FROM jobs WHERE extracted_at < ?", (cutoff,))
    conn.commit()


def cmd_prune(args: argparse.Namespace) -> int:
    """Manually prune messages + jobs older than the retention window."""
    conn = db.connect()
    days = args.days if args.days is not None else config.load().get("retention_days", 2)
    _prune(conn, days)
    print(json.dumps({"pruned_older_than_days": days}, ensure_ascii=False, indent=2))
    return 0


# --- pull ----------------------------------------------------------------

def cmd_pull(args: argparse.Namespace) -> int:
    """Scan every source; stash new messages (any post with a URL or text) into
    the DB, after pruning anything older than the retention window."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn = db.connect()
    _prune(conn, config.load().get("retention_days", 2))
    sources = load_sources()

    summary: dict[str, object] = {
        "run_start": now,
        "sources_scanned": 0,
        "messages_fetched": 0,
        "messages_with_urls": 0,
        "new_messages_stored": 0,
        "errors": [],
    }

    if not sources:
        summary["errors"].append({
            "error": f"No sources listed in {config.sources_file()}. "
                     "Add at least one channel and run /tg-intent again.",
        })
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    for ref in sources:
        cursor_row = conn.execute(
            "SELECT last_msg_id FROM channels WHERE ref = ?", (ref,)
        ).fetchone()
        last_id = int(cursor_row["last_msg_id"]) if cursor_row else 0

        cmd = [
            "uv", "run", "--with", "telethon",
            "python", str(TG_SCAN), "scan",
            "--channel", ref,
            "--limit", str(CHANNEL_MSG_LIMIT),
        ]
        if last_id > 0:
            cmd += ["--min-id", str(last_id)]
        else:
            cmd += ["--days", str(FIRST_SCAN_DAYS)]

        print(f"[pull] {ref}  min_id={last_id or 'none'}", file=sys.stderr)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            # `uv` isn't on PATH. Phrase the error so the /tg-intent redirect
            # heuristic ("not set up") fires instead of leaking a raw traceback.
            summary["errors"].append({
                "channel": ref,
                "error": "uv not found on PATH — the scanner is not set up. "
                         "Install uv or run /tg-intent-setup.",
            })
            break
        if not proc.stdout.strip():
            summary["errors"].append({
                "channel": ref,
                "error": f"tg_scan failed rc={proc.returncode}: {proc.stderr.strip()[:300]}",
            })
            continue
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            summary["errors"].append({
                "channel": ref,
                "error": f"invalid JSON from tg_scan: {exc}",
            })
            continue

        summary["errors"].extend(payload.get("errors") or [])
        msgs = payload.get("messages") or []
        summary["sources_scanned"] = int(summary["sources_scanned"]) + 1
        summary["messages_fetched"] = int(summary["messages_fetched"]) + len(msgs)

        max_msg_id = last_id
        title = None
        new_stored = 0
        for m in msgs:
            if m.get("channel_title"):
                title = m["channel_title"]
            mid = int(m["msg_id"])
            if mid > max_msg_id:
                max_msg_id = mid
            urls = m.get("urls") or []
            text = m.get("text") or ""
            if not urls and not text.strip():
                continue          # skip pure media / service messages
            if urls:
                summary["messages_with_urls"] = int(summary["messages_with_urls"]) + 1
            before = conn.total_changes
            conn.execute(
                "INSERT OR IGNORE INTO messages"
                "(channel_ref, msg_id, msg_date, permalink, text, urls_json, is_processed, fetched_at)"
                " VALUES(?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    ref, mid, m.get("date"), m.get("permalink"),
                    text, json.dumps(urls, ensure_ascii=False),
                    now,
                ),
            )
            if conn.total_changes > before:
                new_stored += 1

        conn.execute(
            "INSERT INTO channels(ref, title, last_msg_id, last_scanned_at)"
            " VALUES(?, ?, ?, ?)"
            " ON CONFLICT(ref) DO UPDATE SET"
            "   title = COALESCE(excluded.title, channels.title),"
            "   last_msg_id = MAX(channels.last_msg_id, excluded.last_msg_id),"
            "   last_scanned_at = excluded.last_scanned_at",
            (ref, title or ref, max_msg_id, now),
        )
        conn.commit()
        summary["new_messages_stored"] = int(summary["new_messages_stored"]) + new_stored
        print(f"[pull] {ref}: {len(msgs)} msgs, {new_stored} new with links",
              file=sys.stderr)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


# --- unclassified --------------------------------------------------------

def cmd_unclassified(args: argparse.Namespace) -> int:
    """Print JSON of messages awaiting classification (is_processed = 0)."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT channel_ref, msg_id, msg_date, permalink, text, urls_json"
        " FROM messages WHERE is_processed = 0"
        " ORDER BY msg_date DESC LIMIT ?",
        (args.limit,),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "channel_ref": r["channel_ref"],
            "msg_id": r["msg_id"],
            "date": r["msg_date"],
            "permalink": r["permalink"],
            "text": r["text"],
            "urls": json.loads(r["urls_json"]) if r["urls_json"] else [],
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


# --- save-classifications -----------------------------------------------

def _matched_intents(ex: dict, declared_map: dict, has_headers: bool):
    """Resolve which intents an extraction matched, as canonical names.

    Returns a list of canonical intent names, or None for a genuine no-match.

    Precedence: an explicit `intents` list wins; a singular `intent` string is
    accepted next; `is_match` is consulted only when neither is present.
    Names the classifier returns are reconciled to the DECLARED set (exact,
    then NFC+casefold+whitespace match) — unrecognized/hallucinated names are
    dropped, never minted into a new file. The stored value is always the
    canonical declared name, so file names and headers can't drift.
    """
    raw_intents = ex.get("intents")
    if isinstance(raw_intents, list):
        out: list[str] = []
        seen: set[str] = set()
        for item in raw_intents:
            if not isinstance(item, str):
                continue
            canon = declared_map.get(_canon_intent(item))
            if canon is None:
                continue  # unknown/drifted name — drop
            if canon in seen:
                continue
            seen.add(canon)
            out.append(canon)
        if out:
            return out
        # An (effectively) empty intents list from a headered file is an
        # authoritative no-match. With no headers it just means "use is_match".
        if has_headers:
            return None
    elif isinstance(raw_intents, str):
        canon = declared_map.get(_canon_intent(raw_intents))
        if canon is not None:
            return [canon]
        if has_headers:
            return None

    single = ex.get("intent")
    if isinstance(single, str) and single.strip():
        canon = declared_map.get(_canon_intent(single))
        if canon is not None:
            return [canon]
        if has_headers:
            return None

    # Legacy / headerless-default path: a plain is_match verdict files the role
    # under the default intent ''.
    if ex.get("is_match"):
        return [""]
    return None


def cmd_save_classifications(args: argparse.Namespace) -> int:
    """Ingest the classifier's verdicts.

    Expected JSON shape (list, one entry per message):

        [
          {
            "channel_ref": "@somejobs",
            "msg_id": 12345,
            "extractions": [
              {
                "link": "https://...",
                "position": "Product Manager",
                "company": "Acme",
                "is_job": true,               // a real single open role?
                "intents": ["Product Manager"] // which declared intents it fits
              }
            ]
          }
        ]

    `intents` lists the declared `## Intent:` names the role matches (a role may
    match several). Files with no intents use the legacy `is_match` boolean, and
    those rows land under the default intent ''. A vacancy is stored once per
    matched intent (deduped by link+intent). Every listed message is marked
    processed regardless, so the next run doesn't re-classify it.
    """
    raw = args.json
    if raw == "-" or raw is None:
        raw = sys.stdin.read()
    payload = json.loads(raw)

    # The classifier is an LLM; tolerate common deviations from the documented
    # top-level array (an object wrapper, or a stray null) instead of crashing
    # the whole ingest on a raw traceback.
    if isinstance(payload, dict):
        for _k in ("classifications", "results", "entries", "items"):
            if isinstance(payload.get(_k), list):
                payload = payload[_k]
                break
        else:
            payload = []
    if not isinstance(payload, list):
        payload = []

    conn = db.connect()
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    # Canonical declared intents drive reconciliation: the classifier's names
    # are matched against THIS set, never used raw. Empty set → default search.
    declared = load_intents()
    declared_map = {_canon_intent(n): n for n in declared}
    has_headers = bool(declared)

    msgs_processed = 0
    jobs_matched = 0
    jobs_skipped_nomatch = 0
    jobs_skipped_dupe = 0
    jobs_skipped_bad = 0

    for entry in payload:
        if not isinstance(entry, dict):
            continue
        ch = entry.get("channel_ref")
        mid = entry.get("msg_id")
        if ch is None or mid is None:
            continue
        msg_row = conn.execute(
            "SELECT permalink, msg_date FROM messages"
            " WHERE channel_ref = ? AND msg_id = ?",
            (ch, mid),
        ).fetchone()
        msg_permalink = msg_row["permalink"] if msg_row else None
        msg_date = msg_row["msg_date"] if msg_row else None

        exs = entry.get("extractions")
        if not isinstance(exs, list):
            exs = []
        for ex in exs:
            if not isinstance(ex, dict) or not ex.get("is_job"):
                continue
            intents = _matched_intents(ex, declared_map, has_headers)
            if not intents:
                jobs_skipped_nomatch += 1
                continue
            link = (ex.get("link") or "").strip()
            link_norm = db.normalize_url(link)
            if not link_norm:
                jobs_skipped_bad += 1
                continue
            position = (ex.get("position").strip() if isinstance(ex.get("position"), str) else "")
            company = (ex.get("company").strip() if isinstance(ex.get("company"), str) else "")
            excerpt = (ex.get("excerpt").strip()[:200] if isinstance(ex.get("excerpt"), str) else "")
            for intent in intents:
                before = conn.total_changes
                conn.execute(
                    "INSERT OR IGNORE INTO jobs(link_norm, intent, link, position,"
                    " company, msg_permalink, msg_date, channel_ref, excerpt, extracted_at)"
                    " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        link_norm, intent, link, position, company,
                        msg_permalink, msg_date, ch, excerpt, now,
                    ),
                )
                if conn.total_changes > before:
                    jobs_matched += 1
                else:
                    jobs_skipped_dupe += 1

        conn.execute(
            "UPDATE messages SET is_processed = 1"
            " WHERE channel_ref = ? AND msg_id = ?",
            (ch, mid),
        )
        msgs_processed += 1

    conn.commit()
    print(json.dumps({
        "messages_processed": msgs_processed,
        "jobs_matched": jobs_matched,
        "jobs_skipped_no_match": jobs_skipped_nomatch,
        "jobs_skipped_dupe": jobs_skipped_dupe,
        "jobs_skipped_bad_link": jobs_skipped_bad,
    }, ensure_ascii=False, indent=2))
    return 0


# --- emit-files ----------------------------------------------------------

# Wording of each emitted output file, per config `lang`. `prefix` is the file
# name of the DEFAULT (headerless) intent; named intents are filed under their
# own name. Everything else the user sees is localized by the agent; these
# files are written directly by Python, so they carry their own i18n.
_EMIT_I18N = {
    "en": {
        "prefix": "matches",
        "title": "Matching vacancies",
        "generated": "Generated by /tg-intent at {when}. Rows: {n}.",
        "columns": "| Position | Company | Links | Date | Telegram post |",
        "excerpt_col": "Excerpt",
    },
    "ru": {
        "prefix": "вакансии",
        "title": "Подходящие вакансии",
        "generated": "Сгенерировано /tg-intent: {when}. Строк: {n}.",
        "columns": "| Должность | Компания | Ссылки | Дата | Пост в Telegram |",
        "excerpt_col": "Выдержка",
    },
}


def _md_cell(v: str) -> str:
    return (v or "").replace("\n", " ").replace("|", "\\|").strip()


def _render_table(rows: list[sqlite3.Row], when_iso: str, lang: str = "en",
                  intent: str = "") -> str:
    # Group by (position, company). Rows are pre-sorted by msg_date DESC, so
    # the first appearance of a key fixes the group's position. Extra links /
    # posts for that group append to bulleted cells. Rows with empty position
    # AND company are keyed by link so they don't collapse together.
    groups: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for r in rows:
        pos = (r["position"] or "").strip()
        co = (r["company"] or "").strip()
        link = (r["link"] or "").strip()
        tg = (r["msg_permalink"] or "").strip()
        ex = (r["excerpt"] or "").strip() if "excerpt" in r.keys() else ""
        d = r["msg_date"] or ""
        key = (pos.lower(), co.lower()) if (pos or co) else (link.lower(), "")
        g = groups.get(key)
        if g is None:
            g = {"position": pos, "company": co,
                 "links": [], "tg_posts": [], "excerpt": ex, "latest_date": d}
            groups[key] = g
            order.append(key)
        if link and link not in g["links"]:
            g["links"].append(link)
        if tg and tg not in g["tg_posts"]:
            g["tg_posts"].append(tg)
        if not g["excerpt"] and ex:
            g["excerpt"] = ex
        if d > g["latest_date"]:
            g["latest_date"] = d

    def bullets(items: list[str]) -> str:
        return "<br>".join(f"• {x}" for x in items)

    s = _EMIT_I18N.get(lang, _EMIT_I18N["en"])
    heading = s["title"] + (f" — {intent}" if intent else "")
    lines = [
        f"# {heading}",
        "",
        s["generated"].format(when=when_iso, n=len(order)),
        "",
        f"{s['columns']} {s['excerpt_col']} |",
        "|---|---|---|---|---|---|",
    ]
    for key in order:
        g = groups[key]
        pos = _md_cell(g["position"])
        co = _md_cell(g["company"])
        links = _md_cell(bullets(g["links"]))
        date_only = g["latest_date"][:10]
        tgs = _md_cell(bullets(g["tg_posts"]))
        lines.append(f"| {pos} | {co} | {links} | {date_only} | {tgs} | {_md_cell(g['excerpt'])} |")
    lines.append("")
    return "\n".join(lines)


def _norm_key(s: str) -> str:
    """Collapse whitespace + lowercase, for comparing company/position across
    postings that differ only in spacing or case."""
    return " ".join((s or "").split()).lower()


def cmd_emit_files(args: argparse.Namespace) -> int:
    """Write ONE file per intent (since --since), localized per config lang.

    Rows are grouped by their stored intent. The default intent '' keeps the
    localized matches+/вакансии+ name; every other intent gets a file named
    after it. Export-time suppression is scoped per-intent so one intent's
    recent hit can't hide another intent's brand-new role."""
    since = args.since or "1970-01-01T00:00:00+00:00"
    conn = db.connect()
    cfg = config.load()
    lang = cfg["lang"]
    dedup_days = int(cfg.get("export_dedup_days", 3))
    prefix = _EMIT_I18N.get(lang, _EMIT_I18N["en"])["prefix"]

    rows = conn.execute(
        "SELECT position, company, link, msg_date, msg_permalink, excerpt, intent"
        " FROM jobs WHERE extracted_at >= ?"
        " ORDER BY msg_date DESC, position ASC",
        (since,),
    ).fetchall()

    # Bucket this run's rows by intent. `key` is the canonical comparison key
    # ('' for the default); `display` is the exact stored intent string, used
    # both for the filename and for the per-intent suppression query below
    # (save-classifications always stores the canonical declared name, so all
    # of an intent's rows share one exact string).
    buckets: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        intent = r["intent"] or ""
        key = _canon_intent(intent)
        b = buckets.get(key)
        if b is None:
            b = {"display": intent, "rows": []}
            buckets[key] = b
            order.append(key)
        b["rows"].append(r)

    # Surface declared intents that matched nothing this run (written = 0), so
    # the agent can distinguish "skipped, no matches" from a stale old file.
    for name in load_intents():
        key = _canon_intent(name)
        if key not in buckets:
            buckets[key] = {"display": name, "rows": []}
            order.append(key)

    window_start = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=dedup_days)
    ).isoformat()
    now_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = cfg["folder"]
    out_dir.mkdir(parents=True, exist_ok=True)

    # The localized default name is reserved so a user intent can't collide
    # with it (both en + ru prefixes, defensively).
    reserved = {_canon_intent(v["prefix"]) for v in _EMIT_I18N.values()}
    used_norm: set[str] = set()

    files: list[dict] = []
    fallback_idx = 0
    for key in order:
        fallback_idx += 1
        b = buckets[key]
        display = b["display"]
        brows = b["rows"]
        is_default = key == ""

        # Per-intent export suppression (scoped to THIS intent only).
        suppressed = 0
        if args.since and dedup_days > 0 and brows:
            prior = conn.execute(
                "SELECT DISTINCT company, position FROM jobs"
                " WHERE extracted_at >= ? AND extracted_at < ? AND intent = ?",
                (window_start, since, display),
            ).fetchall()
            seen = {
                (_norm_key(pr["company"]), _norm_key(pr["position"]))
                for pr in prior
                if (pr["company"] or "").strip() and (pr["position"] or "").strip()
            }
            if seen:
                kept = []
                for r in brows:
                    co, pos = (r["company"] or "").strip(), (r["position"] or "").strip()
                    if co and pos and (_norm_key(co), _norm_key(pos)) in seen:
                        suppressed += 1
                        continue
                    kept.append(r)
                brows = kept

        path_str = None
        if brows:
            if is_default:
                # The default file may legitimately use the reserved name.
                path = _resolve_out_path(out_dir, prefix, stamp, used_norm, set())
            else:
                base = _sanitize_filename_base(display, fallback_idx)
                path = _resolve_out_path(out_dir, base, stamp, used_norm, reserved)
            path.write_text(
                _render_table(brows, now_utc, lang, intent=display),
                encoding="utf-8",
            )
            path_str = str(path)

        files.append({
            "intent": display,
            "path": path_str,
            "written": len(brows),
            "suppressed": suppressed,
        })

    print(json.dumps({
        "files": files,
        "matches_written": sum(f["written"] for f in files),
        "suppressed_recent": sum(f["suppressed"] for f in files),
    }, ensure_ascii=False, indent=2))
    return 0


# --- entry point ---------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram job scanner.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pull", help="Fetch new TG messages into the DB.")

    p_unc = sub.add_parser("unclassified", help="Print pending TG messages as JSON.")
    p_unc.add_argument("--limit", type=int, default=100)

    p_save = sub.add_parser("save-classifications", help="Ingest the classifier's verdicts.")
    p_save.add_argument("--json", required=True,
                        help="JSON string with classifications, or '-' for stdin.")

    p_emit = sub.add_parser("emit-files", help="Write one <intent>+<stamp>.md file per intent.")
    p_emit.add_argument("--since", default=None,
                        help="ISO timestamp; only include jobs extracted_at >= SINCE.")

    p_prune = sub.add_parser("prune", help="Delete messages + jobs older than the retention window.")
    p_prune.add_argument("--days", type=int, default=None,
                         help="Retention window in days; defaults to config retention_days.")

    args = parser.parse_args()
    handler = {
        "pull": cmd_pull,
        "unclassified": cmd_unclassified,
        "save-classifications": cmd_save_classifications,
        "emit-files": cmd_emit_files,
        "prune": cmd_prune,
    }[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
