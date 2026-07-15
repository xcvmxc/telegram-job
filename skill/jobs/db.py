#!/usr/bin/env python3
"""SQLite backend for the Telegram job scanner.

Tables:

- channels    one row per Telegram source. `last_msg_id` is the resume
              cursor — the next scan fetches only messages with
              msg_id > last_msg_id.

- messages    raw Telegram posts that contain at least one URL.
              `is_processed` flips to 1 after the classifier has looked
              at the message, so it's never re-classified.

- jobs        deduped vacancies that MATCHED the user's search criteria.
              Dedup key is `link_norm`. Non-matching postings are not
              stored here — their message is simply marked processed.

State lives at ~/.claude/jobs/jobs.db (override with JOBS_DB for testing).

Stdlib only.
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import urllib.parse

DB_PATH = pathlib.Path(
    os.environ.get("JOBS_DB") or (pathlib.Path.home() / ".claude" / "jobs" / "jobs.db")
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

CREATE TABLE IF NOT EXISTS jobs (
    link_norm     TEXT PRIMARY KEY,
    link          TEXT NOT NULL,
    position      TEXT,
    company       TEXT,
    msg_permalink TEXT,
    msg_date      TEXT,
    channel_ref   TEXT,
    extracted_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_jobs_extracted_at ON jobs(extracted_at);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
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
