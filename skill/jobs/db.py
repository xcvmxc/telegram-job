#!/usr/bin/env python3
"""SQLite backend for the Telegram job scanner.

Tables:

- channels    one row per Telegram source. `last_msg_id` is the resume
              cursor — the next scan fetches only messages with
              msg_id > last_msg_id.

- messages    raw Telegram posts that contain at least one URL or non-empty text.
              `is_processed` flips to 1 after the classifier has looked
              at the message, so it's never re-classified.

- jobs        deduped vacancies that MATCHED the user's search criteria.
              Dedup key is (link_norm, intent): the same posting can be filed
              under several intents (each intent is an independent search with
              its own export file), but never twice under one intent. Rows in
              the default (headerless) search carry intent = '' (empty string).

State lives at $TGJOBS_HOME/jobs/jobs.db (default ~/.tgjobs; override with
TGJOBS_HOME, or JOBS_DB for the DB path directly).

Stdlib only.
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import urllib.parse

TGJOBS_HOME = pathlib.Path(
    os.environ.get("TGJOBS_HOME") or (pathlib.Path.home() / ".tgjobs")
)
DB_PATH = pathlib.Path(
    os.environ.get("JOBS_DB") or (TGJOBS_HOME / "jobs" / "jobs.db")
)

# The jobs table body is factored out so the fresh-install path (_SCHEMA) and
# the migration path (jobs_new) build IDENTICAL tables — same columns, same
# NOT NULL DEFAULT, same composite PRIMARY KEY — and can never drift.
_JOBS_BODY = """(
    link_norm     TEXT NOT NULL,
    intent        TEXT NOT NULL DEFAULT '',
    link          TEXT NOT NULL,
    position      TEXT,
    company       TEXT,
    msg_permalink TEXT,
    msg_date      TEXT,
    channel_ref   TEXT,
    excerpt       TEXT,
    extracted_at  TEXT NOT NULL,
    PRIMARY KEY (link_norm, intent)
)"""

# Columns copied verbatim when rebuilding jobs during migration. Listed
# explicitly (never SELECT *) because an excerpt-migrated DB has excerpt AFTER
# extracted_at, so positional copy would shove excerpt into extracted_at and
# corrupt the prune/dedup timestamp key.
_JOBS_COPY_COLS = (
    "link_norm, link, position, company, msg_permalink,"
    " msg_date, channel_ref, excerpt, extracted_at"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    ref             TEXT PRIMARY KEY,
    title           TEXT,
    last_msg_id     INTEGER NOT NULL DEFAULT 0,
    last_scanned_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    channel_ref  TEXT NOT NULL,
    msg_id       INTEGER NOT NULL,
    msg_date     TEXT,
    permalink    TEXT,
    text         TEXT,
    urls_json    TEXT,
    is_processed INTEGER NOT NULL DEFAULT 0,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (channel_ref, msg_id)
);

CREATE INDEX IF NOT EXISTS ix_messages_processed
    ON messages(is_processed);

CREATE TABLE IF NOT EXISTS jobs """ + _JOBS_BODY + """;

CREATE INDEX IF NOT EXISTS ix_jobs_extracted_at ON jobs(extracted_at);
"""


def _migrate_add_intent(conn: sqlite3.Connection) -> None:
    """Rebuild the pre-intent `jobs` table (single-column PK on link_norm) into
    the composite-PK (link_norm, intent) shape, filing every existing row under
    the default intent ''.

    This is the ONLY code path that introduces the `intent` column: it must add
    the column AND the composite key together. A plain `ALTER TABLE ADD COLUMN
    intent` is forbidden — it would add the column while leaving the old
    single-column PK, silently breaking multi-intent dedup while making the
    idempotency guard think the migration already ran.

    Wrapped in one explicit transaction with rollback so a crash or bad row
    can't strand data between DROP and RENAME. `DROP TABLE IF EXISTS jobs_new`
    up front defuses a wedge from a previously aborted attempt.
    """
    prev_isolation = conn.isolation_level
    conn.isolation_level = None  # manual transaction control
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DROP TABLE IF EXISTS jobs_new")
        conn.execute("CREATE TABLE jobs_new " + _JOBS_BODY)
        conn.execute(
            "INSERT INTO jobs_new (" + _JOBS_COPY_COLS + ", intent)"
            " SELECT " + _JOBS_COPY_COLS + ", '' FROM jobs"
        )
        conn.execute("DROP TABLE jobs")
        conn.execute("ALTER TABLE jobs_new RENAME TO jobs")
        # Recreate the index only after the old table (and its identically-named
        # index) is gone and jobs_new has taken the name.
        conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_extracted_at ON jobs(extracted_at)")
        conn.execute("COMMIT")
    except Exception:
        # conn.rollback() (the method) is a no-op when no transaction is open,
        # so a failed BEGIN IMMEDIATE (e.g. "database is locked") propagates its
        # real error instead of being masked by "cannot rollback" — unlike a
        # raw `execute("ROLLBACK")`, which raises when no transaction is active.
        conn.rollback()
        raise
    finally:
        conn.isolation_level = prev_isolation


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    # Lightweight migration for DBs created before `excerpt` existed. Must run
    # BEFORE the intent rebuild, whose copy SELECT references excerpt.
    if cols and "excerpt" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN excerpt TEXT")
        conn.commit()
        cols.add("excerpt")
    # Migrate pre-intent DBs to the composite (link_norm, intent) key. Fresh
    # DBs already have `intent` from _SCHEMA, so this never fires for them.
    if cols and "intent" not in cols:
        _migrate_add_intent(conn)
    return conn


_STRIP_PARAMS = {"ref", "gh_src", "lever-source", "source"}


def normalize_url(u: str) -> str:
    """Lowercased scheme+host, path without trailing slash, tracking params
    stripped. Used as the dedup key for vacancies."""
    u = (u or "").strip()
    if not u:
        return u
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return u.rstrip("/")
    if not p.scheme:
        return u.rstrip("/").lower()
    host = p.netloc.lower()
    q = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in _STRIP_PARAMS and not k.lower().startswith("utm_")
    ]
    path = p.path.rstrip("/")
    query = urllib.parse.urlencode(q)
    return urllib.parse.urlunsplit((p.scheme.lower(), host, path, query, ""))
