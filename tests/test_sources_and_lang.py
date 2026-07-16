#!/usr/bin/env python3
"""Tests for Active/Inactive source sections and install-time language flow.

Stdlib only (unittest). Run:  python3 tests/test_sources_and_lang.py
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skill" / "jobs"))

import config  # noqa: E402
import db       # noqa: E402
import scan     # noqa: E402
import setup     # noqa: E402


class TestActiveInactive(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.out = self.tmp / "out"
        self.out.mkdir(parents=True)
        config.CONFIG_PATH = self.tmp / "config.json"
        db.DB_PATH = self.tmp / "jobs.db"
        config.CONFIG_PATH.write_text(json.dumps({"folder": str(self.out), "lang": "en"}))

    def write(self, text):
        (self.out / config.SOURCES_FILENAME).write_text(text, encoding="utf-8")

    def test_only_active_scanned(self):
        self.write(
            "# header comment\n## Active\n- @a\n@b\n-1001234567890\n"
            "## Inactive\n- @c\n@d\n"
        )
        self.assertEqual(scan.load_sources(), ["@a", "@b", "-1001234567890"])

    def test_russian_headers(self):
        self.write("## Активные\n- @a\n## Неактивные\n- @b\n")
        self.assertEqual(scan.load_sources(), ["@a"])

    def test_no_headers_is_backward_compatible(self):
        self.write("- @a\n@b\n# comment\n-1001234567890\n")
        self.assertEqual(scan.load_sources(), ["@a", "@b", "-1001234567890"])

    def test_commented_examples_not_scanned(self):
        self.write("## Active\n# - @example\n\n## Inactive\n")
        self.assertEqual(scan.load_sources(), [])

    def test_ordinary_comment_is_not_a_section_header(self):
        self.write("# Telegram sources\n## Active\n@a\n# ACCEPTED FORMATS\n@b\n")
        self.assertEqual(scan.load_sources(), ["@a", "@b"])

    def test_active_after_inactive_resumes(self):
        self.write("## Inactive\n@a\n## Active\n@b\n")
        self.assertEqual(scan.load_sources(), ["@b"])

    def test_shipped_templates_parse_to_empty(self):
        for lang in ("en", "ru"):
            tpl = (HERE.parent / "templates" / lang / "Telegram Sources.md").read_text(encoding="utf-8")
            self.write(tpl)
            self.assertEqual(scan.load_sources(), [], f"{lang} template should have no live refs")


class TestInstallLang(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        config.TGJOBS_HOME = self.tmp
        config.CONFIG_PATH = self.tmp / "config.json"
        setup.TEMPLATES_DIR = HERE.parent / "templates"
        self.out = self.tmp / "out"

    def _init(self, lang_arg):
        ns = types.SimpleNamespace(folder=str(self.out), lang=lang_arg)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            setup.cmd_init(ns)
        return json.loads(config.CONFIG_PATH.read_text())["lang"]

    def test_lang_defaults_to_installed(self):
        (self.tmp / "installed.json").write_text(json.dumps({"lang": "ru", "agents": ["claude"]}))
        self.assertEqual(self._init(None), "ru")  # no --lang -> install choice

    def test_explicit_lang_wins(self):
        (self.tmp / "installed.json").write_text(json.dumps({"lang": "ru"}))
        self.assertEqual(self._init("en"), "en")

    def test_fallback_when_no_installed_json(self):
        self.assertEqual(self._init(None), "en")

    def test_ignores_garbage_installed_json(self):
        (self.tmp / "installed.json").write_text("not json {")
        self.assertEqual(self._init(None), "en")


if __name__ == "__main__":
    unittest.main(verbosity=2)
