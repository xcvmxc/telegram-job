#!/usr/bin/env python3
"""Tests for the multi-intent Search Criteria feature.

Stdlib only (unittest). Run:  python3 tests/test_multi_intent.py

Each test runs against an isolated temp TGJOBS_HOME/DB/folder by pointing the
config + db module globals at temp paths, so nothing touches ~/.tgjobs.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skill" / "jobs"))

import config  # noqa: E402
import db       # noqa: E402
import scan     # noqa: E402


def _iso(days_ago: float = 0) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.out = self.tmp / "out"
        self.out.mkdir(parents=True)
        config.CONFIG_PATH = self.tmp / "config.json"
        db.DB_PATH = self.tmp / "jobs.db"

    def write_config(self, lang="en", dedup=3, retention=3):
        config.CONFIG_PATH.write_text(json.dumps({
            "folder": str(self.out), "lang": lang,
            "export_dedup_days": dedup, "retention_days": retention,
        }), encoding="utf-8")

    def write_criteria(self, text):
        (self.out / config.CRITERIA_FILENAME).write_text(text, encoding="utf-8")

    def add_message(self, ch="@jobs", mid=1, permalink="https://t.me/jobs/1"):
        conn = db.connect()
        conn.execute(
            "INSERT OR IGNORE INTO messages(channel_ref,msg_id,msg_date,permalink,"
            "text,urls_json,is_processed,fetched_at) VALUES(?,?,?,?,?,?,0,?)",
            (ch, mid, _iso(0), permalink, "hiring", "[]", _iso(0)),
        )
        conn.commit()

    def save(self, payload):
        ns = types.SimpleNamespace(json=json.dumps(payload))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            scan.cmd_save_classifications(ns)
        return json.loads(buf.getvalue())

    def emit(self, since):
        ns = types.SimpleNamespace(since=since)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            scan.cmd_emit_files(ns)
        return json.loads(buf.getvalue())

    def jobs_rows(self):
        conn = db.connect()
        return conn.execute(
            "SELECT link_norm, intent, position, company, extracted_at, excerpt FROM jobs"
        ).fetchall()


class TestDefaultAndLegacy(Base):
    def test_a_no_header_default_emits_default_file(self):
        self.write_config()
        self.write_criteria("# What I'm looking for\n\nProduct roles, mid to senior.\n")
        self.add_message()
        res = self.save([{
            "channel_ref": "@jobs", "msg_id": 1,
            "extractions": [{
                "link": "https://apply.example.com/pm", "position": "PM",
                "company": "Acme", "is_job": True, "is_match": True,
            }],
        }])
        self.assertEqual(res["jobs_matched"], 1)
        rows = self.jobs_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["intent"], "")  # default bucket

        out = self.emit(_iso(0.01))
        self.assertEqual(out["matches_written"], 1)
        self.assertEqual(len(out["files"]), 1)
        self.assertEqual(out["files"][0]["intent"], "")
        self.assertTrue(pathlib.Path(out["files"][0]["path"]).name.startswith("matches+"))

    def test_b_legacy_is_match_no_intents_lands_in_default(self):
        self.write_config()
        self.write_criteria("Plain criteria, no intents here.\n")
        res = self.save([{
            "channel_ref": "@jobs", "msg_id": 9,
            "extractions": [{
                "link": "https://x.example/1", "position": "PM", "company": "Co",
                "is_job": True, "is_match": True,   # legacy shape, no `intents`
            }],
        }])
        self.assertEqual(res["jobs_matched"], 1)
        rows = self.jobs_rows()
        self.assertEqual([r["intent"] for r in rows], [""])


class TestIntentReconciliation(Base):
    HEADERED = (
        "# Intents\n\n"
        "## Intent: Product Manager\n\n**Looking for:** PM roles.\n\n"
        "## Intent: Data\n\n**Looking for:** analytics.\n"
    )

    def test_c_hallucinated_name_dropped_not_minted(self):
        self.write_config()
        self.write_criteria(self.HEADERED)
        res = self.save([{
            "channel_ref": "@jobs", "msg_id": 2,
            "extractions": [{
                "link": "https://x.example/z", "position": "Wizard", "company": "Co",
                "is_job": True, "intents": ["Totally Made Up Intent"],
            }],
        }])
        self.assertEqual(res["jobs_matched"], 0)
        self.assertEqual(res["jobs_skipped_no_match"], 1)
        self.assertEqual(len(self.jobs_rows()), 0)

    def test_c2_known_name_stored_canonical_and_multi(self):
        self.write_config()
        self.write_criteria(self.HEADERED)
        # classifier returns lower-case + whitespace drift; must reconcile to
        # the canonical declared "Product Manager" and also match "Data".
        res = self.save([{
            "channel_ref": "@jobs", "msg_id": 3,
            "extractions": [{
                "link": "https://x.example/pm", "position": "PM", "company": "Acme",
                "is_job": True, "intents": ["  product   manager ", "data"],
            }],
        }])
        self.assertEqual(res["jobs_matched"], 2)
        intents = sorted(r["intent"] for r in self.jobs_rows())
        self.assertEqual(intents, ["Data", "Product Manager"])

    def test_c3_headered_empty_intents_is_no_match(self):
        self.write_config()
        self.write_criteria(self.HEADERED)
        res = self.save([{
            "channel_ref": "@jobs", "msg_id": 4,
            "extractions": [{
                "link": "https://x.example/none", "is_job": True, "intents": [],
            }],
        }])
        self.assertEqual(res["jobs_matched"], 0)
        self.assertEqual(len(self.jobs_rows()), 0)


class TestPerIntentSuppression(Base):
    def test_d_suppress_in_A_but_emit_in_B(self):
        self.write_config(dedup=3, retention=3)
        self.write_criteria(
            "## Intent: Product Manager\ntext\n\n## Intent: Data\ntext\n"
        )
        since = _iso(0.02)
        # Prior run: same company+position already surfaced under "Product
        # Manager" yesterday (within the dedup window, before `since`).
        conn = db.connect()
        conn.execute(
            "INSERT INTO jobs(link_norm,intent,link,position,company,extracted_at)"
            " VALUES(?,?,?,?,?,?)",
            ("https://old/pm", "Product Manager", "https://old/pm", "PM", "Acme", _iso(1)),
        )
        conn.commit()
        # This run: the same role matches BOTH intents under a new link.
        self.save([{
            "channel_ref": "@jobs", "msg_id": 5,
            "extractions": [{
                "link": "https://new/pm", "position": "PM", "company": "Acme",
                "is_job": True, "intents": ["Product Manager", "Data"],
            }],
        }])
        out = self.emit(since)
        by_intent = {f["intent"]: f for f in out["files"]}
        self.assertEqual(by_intent["Product Manager"]["written"], 0)
        self.assertEqual(by_intent["Product Manager"]["suppressed"], 1)
        self.assertEqual(by_intent["Data"]["written"], 1)
        self.assertEqual(by_intent["Data"]["suppressed"], 0)


class TestFilenames(Base):
    def test_e_case_collision_in_run_bumps_counter(self):
        base = "Product Manager"
        used = set()
        p1 = scan._resolve_out_path(self.out, base, "S", used, set())
        # Different case, same casefold key -> must not reuse p1's name.
        p2 = scan._resolve_out_path(self.out, "product manager", "S", used, set())
        self.assertNotEqual(p1.name, p2.name)
        self.assertTrue(p2.name.startswith("product manager (1)+"))

    def test_e2_existing_file_on_disk_bumps(self):
        (self.out / "Design+S.md").write_text("x", encoding="utf-8")
        p = scan._resolve_out_path(self.out, "Design", "S", set(), set())
        self.assertEqual(p.name, "Design (1)+S.md")

    def test_e3_reserved_and_sanitize(self):
        # a user intent literally named "matches" is forced off the reserved name
        reserved = {scan._canon_intent("matches")}
        p = scan._resolve_out_path(self.out, "matches", "S", set(), reserved)
        self.assertTrue(p.name.startswith("matches (1)+"))
        # unsafe chars and leading dot are stripped
        self.assertEqual(scan._sanitize_filename_base("a/b:c", 1), "a b c")
        self.assertEqual(scan._sanitize_filename_base("...", 1), "intent-1")
        self.assertEqual(scan._sanitize_filename_base(".NET", 1), "NET")


class TestMigration(Base):
    def _make_old_jobs_db(self, extra_leftover=False):
        """Create a pre-intent jobs table with excerpt-ALTER'd column order
        (excerpt physically AFTER extracted_at) and one row."""
        conn = sqlite3.connect(db.DB_PATH)
        conn.execute(
            "CREATE TABLE jobs (link_norm TEXT PRIMARY KEY, link TEXT NOT NULL,"
            " position TEXT, company TEXT, msg_permalink TEXT, msg_date TEXT,"
            " channel_ref TEXT, extracted_at TEXT NOT NULL, excerpt TEXT)"
        )
        conn.execute(
            "INSERT INTO jobs(link_norm,link,position,company,msg_permalink,"
            "msg_date,channel_ref,extracted_at,excerpt) VALUES(?,?,?,?,?,?,?,?,?)",
            ("https://k/1", "https://k/1", "PM", "Acme", "https://t.me/j/1",
             _iso(0), "@jobs", "2026-07-15T10:00:00+00:00", "short excerpt"),
        )
        if extra_leftover:
            conn.execute("CREATE TABLE jobs_new (junk TEXT)")
            conn.execute("INSERT INTO jobs_new VALUES('stale')")
        conn.commit()
        conn.close()

    def test_f_migration_preserves_extracted_at_and_excerpt(self):
        self._make_old_jobs_db()
        conn = db.connect()  # triggers migration
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        self.assertIn("intent", cols)
        row = conn.execute(
            "SELECT intent, extracted_at, excerpt FROM jobs WHERE link_norm=?",
            ("https://k/1",),
        ).fetchone()
        self.assertEqual(row["intent"], "")
        self.assertEqual(row["extracted_at"], "2026-07-15T10:00:00+00:00")
        self.assertEqual(row["excerpt"], "short excerpt")
        # composite PK now allows the same link under a second intent
        conn.execute(
            "INSERT INTO jobs(link_norm,intent,link,extracted_at)"
            " VALUES(?,?,?,?)", ("https://k/1", "Data", "https://k/1", _iso(0)))
        conn.commit()
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM jobs WHERE link_norm=?",
                         ("https://k/1",)).fetchone()[0], 2)

    def test_g_aborted_rebuild_leftover_recovers(self):
        self._make_old_jobs_db(extra_leftover=True)
        conn = db.connect()  # must DROP the stale jobs_new and migrate cleanly
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        self.assertIn("intent", cols)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
        # jobs_new must be gone
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("jobs_new", names)

    def test_h_begin_failure_surfaces_real_error_not_rollback_mask(self):
        # A pre-intent DB whose BEGIN IMMEDIATE fails (another connection holds
        # an EXCLUSIVE lock) must surface the REAL "database is locked" error,
        # not a masking "cannot rollback - no transaction is active".
        c0 = sqlite3.connect(db.DB_PATH)
        c0.execute("CREATE TABLE jobs (link_norm TEXT PRIMARY KEY, link TEXT"
                   " NOT NULL, extracted_at TEXT NOT NULL, excerpt TEXT)")
        c0.commit()
        c0.close()
        locker = sqlite3.connect(db.DB_PATH)
        locker.isolation_level = None
        locker.execute("BEGIN EXCLUSIVE")
        try:
            migrating = sqlite3.connect(db.DB_PATH, timeout=0)  # fail fast
            migrating.row_factory = sqlite3.Row
            with self.assertRaises(sqlite3.OperationalError) as ctx:
                db._migrate_add_intent(migrating)
            msg = str(ctx.exception).lower()
            self.assertIn("lock", msg)
            self.assertNotIn("cannot rollback", msg)
            migrating.close()
        finally:
            locker.execute("ROLLBACK")
            locker.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
