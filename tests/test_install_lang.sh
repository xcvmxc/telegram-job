#!/usr/bin/env bash
#
# Integration test: the install-time language must survive a re-run that adds
# another agent without re-specifying --lang (regression for the "re-run resets
# language to en" bug). Runs install.sh twice against a throwaway HOME.
#
#   bash tests/test_install_lang.sh
#
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
mkdir -p "$HOME"
unset TGJOBS_HOME 2>/dev/null || true   # let it default to $HOME/.tgjobs
IJ="$HOME/.tgjobs/installed.json"

get() { python3 -c "import json,sys;print(json.load(open('$IJ'))$1)"; }

# 1) Fresh install in Russian, Claude only.
bash "$REPO/install.sh" --lang ru --agent claude -y >/dev/null 2>&1
[ "$(get "['lang']")" = ru ] || { echo "FAIL: first install lang=$(get "['lang']") (want ru)"; exit 1; }

# 2) Re-run to add Codex WITHOUT --lang — must inherit ru, not reset to en.
bash "$REPO/install.sh" --agent codex -y >/dev/null 2>&1
lang="$(get "['lang']")"
[ "$lang" = ru ] || { echo "FAIL: re-run reset language to '$lang' (want ru)"; exit 1; }

# agents must have accumulated (claude + codex) and the ru wizard must be installed.
agents="$(get "['agents']")"
case "$agents" in *claude*) ;; *) echo "FAIL: claude dropped from agents ($agents)"; exit 1;; esac
case "$agents" in *codex*)  ;; *) echo "FAIL: codex not added ($agents)"; exit 1;; esac
grep -q "по-русски" "$HOME/.claude/commands/tg-intent.md" \
  || { echo "FAIL: Russian adapter not installed for Claude after re-run"; exit 1; }

echo "OK: language preserved=ru across re-run; agents=$agents"
