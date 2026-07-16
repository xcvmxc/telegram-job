#!/usr/bin/env bash
#
# Installer for the Telegram job scanner.
#
# Installs a shared, agent-neutral backend into ~/.tgjobs and a thin /tg-intent
# command adapter into each LLM coding agent you choose (Claude Code, Codex,
# Gemini CLI, Cursor). Interactive by default; re-run any time to add another
# agent. Your state (~/.tgjobs/jobs/jobs.db) and config are never touched.
#
# Easiest (no clone):
#   curl -fsSL https://raw.githubusercontent.com/xcvmxc/telegram-intent/main/install.sh | bash
#
# Non-interactive:
#   ./install.sh --lang en --agent claude,codex
#   curl -fsSL .../install.sh | bash -s -- --lang ru --agent all
#
# Update everything already installed (all agents at once, keeps state):
#   curl -fsSL .../install.sh | bash -s -- --update
#
set -euo pipefail

REPO="xcvmxc/telegram-intent"
BRANCH="main"
TARBALL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"

TGJOBS_HOME="${TGJOBS_HOME:-$HOME/.tgjobs}"   # absolute; adapters + configs use this
TS="$(date +%Y%m%d-%H%M%S)"

say()  { printf '  %s\n' "$1"; }
head() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# --- args ----------------------------------------------------------------
AGENTS=""; LANG_CHOICE=""; ASSUME_YES=0; DO_UPDATE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --agent) AGENTS="${2:-}"; shift 2;;
    --agent=*) AGENTS="${1#*=}"; shift;;
    --lang) LANG_CHOICE="${2:-}"; shift 2;;
    --lang=*) LANG_CHOICE="${1#*=}"; shift;;
    --update) DO_UPDATE=1; shift;;
    -y|--yes) ASSUME_YES=1; shift;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 1;;
  esac
done

# Read a line from the real terminal even when the script is piped via curl.
tty_read() {  # tty_read VAR PROMPT
  local __v="$1" __p="$2" __ans=""
  # Probe by actually opening /dev/tty for write — the node can exist yet fail
  # to open (ENXIO "Device not configured") when there's no controlling tty.
  if { : > /dev/tty; } 2>/dev/null; then
    printf '%s' "$__p" > /dev/tty 2>/dev/null || true
    IFS= read -r __ans < /dev/tty 2>/dev/null || __ans=""
  fi
  printf -v "$__v" '%s' "$__ans"
}

head "Telegram job scanner — install"

# --- prerequisites -------------------------------------------------------
command -v python3 >/dev/null 2>&1 || { say "✗ python3 is required."; exit 1; }
if ! command -v uv >/dev/null 2>&1; then
  say "⚠  'uv' is not installed — install it, then re-run:"
  say "     curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

# --- update mode: reuse what's already installed -------------------------
# `--update` refreshes the shared backend AND re-drops the adapter into every
# agent this skill was installed in (from installed.json), at the same language.
if [ "$DO_UPDATE" -eq 1 ]; then
  IJ="$TGJOBS_HOME/installed.json"
  [ -f "$IJ" ] || { say "✗ nothing to update — $IJ not found. Run the installer first."; exit 1; }
  AGENTS="$(python3 - "$IJ" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    a = d.get("agents") if isinstance(d, dict) and isinstance(d.get("agents"), list) else []
except Exception:
    a = []
print(",".join(x for x in a if isinstance(x, str)))
PY
)"
  LANG_CHOICE="$(python3 - "$IJ" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1])); l = d.get("lang") if isinstance(d, dict) else None
except Exception:
    l = None
print(l if l in ("en", "ru") else "en")
PY
)"
  ASSUME_YES=1
  [ -n "$AGENTS" ] || { say "✗ installed.json lists no agents (or is corrupt) — re-run the installer normally."; exit 1; }
  say "Updating agents from installed.json: $AGENTS (language: $LANG_CHOICE)"
fi

# --- locate product files (local checkout or download) -------------------
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "${SELF_DIR}" ] && [ -f "${SELF_DIR}/adapters/en/tg-intent.md" ]; then
  ROOT="${SELF_DIR}"
else
  command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1 || { say "✗ curl and tar are required."; exit 1; }
  say "Downloading…"
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  curl -fsSL "$TARBALL" | tar -xz -C "$TMP" || { say "✗ download failed."; exit 1; }
  ROOT="$(cd "$TMP"/*/ && pwd)"
fi
VER="$(cat "$ROOT/VERSION" 2>/dev/null || echo 0.0.0)"

# --- detect agents -------------------------------------------------------
detect() { # detect NAME  -> echo "yes"/"no"
  case "$1" in
    claude) { command -v claude >/dev/null 2>&1 || [ -d "$HOME/.claude" ]; } && echo yes || echo no;;
    codex)  { command -v codex  >/dev/null 2>&1 || [ -d "$HOME/.codex"  ]; } && echo yes || echo no;;
    gemini) { command -v gemini >/dev/null 2>&1 || [ -d "$HOME/.gemini" ]; } && echo yes || echo no;;
    cursor) { command -v cursor >/dev/null 2>&1 || command -v cursor-agent >/dev/null 2>&1 || [ -d "$HOME/.cursor" ]; } && echo yes || echo no;;
  esac
}
D_claude=$(detect claude); D_codex=$(detect codex); D_gemini=$(detect gemini); D_cursor=$(detect cursor)

# --- choose language -----------------------------------------------------
if [ -z "$LANG_CHOICE" ] && [ "$ASSUME_YES" -eq 0 ]; then
  head "Language / Язык"
  say "1) English   2) Русский"
  tty_read _l "  Choose [1]: "
  case "$_l" in 2|ru|RU|Ru) LANG_CHOICE=ru;; *) LANG_CHOICE=en;; esac
fi
case "${LANG_CHOICE:-en}" in ru) LANG_CHOICE=ru;; *) LANG_CHOICE=en;; esac
say "Language: ${LANG_CHOICE}"

# --- choose agents -------------------------------------------------------
mark() { [ "$1" = yes ] && printf '[detected]' || printf '[not found]'; }
if [ -z "$AGENTS" ] && [ "$ASSUME_YES" -eq 0 ]; then
  head "Which agents should get /tg-intent?"
  say "1) Claude Code  $(mark "$D_claude")"
  say "2) Codex        $(mark "$D_codex")"
  say "3) Gemini CLI   $(mark "$D_gemini")"
  say "4) Cursor       $(mark "$D_cursor")"
  say "Enter numbers separated by space (e.g. \"1 2\"), 'all', or Enter for detected."
  tty_read _a "  Choose: "
  AGENTS="$_a"
fi
# Normalise selection -> space list of names
sel=""
add() { case " $sel " in *" $1 "*) ;; *) sel="$sel $1";; esac; }
if [ "$AGENTS" = all ]; then
  add claude; add codex; add gemini; add cursor
elif [ -z "$AGENTS" ]; then
  # No explicit choice -> only the agents actually present on this machine.
  if [ "$D_claude" = yes ]; then add claude; fi
  if [ "$D_codex"  = yes ]; then add codex;  fi
  if [ "$D_gemini" = yes ]; then add gemini; fi
  if [ "$D_cursor" = yes ]; then add cursor; fi
else
  for tok in $(printf '%s' "$AGENTS" | tr ',' ' '); do
    case "$tok" in
      1|claude) add claude;; 2|codex) add codex;;
      3|gemini) add gemini;; 4|cursor) add cursor;;
      *) say "(ignoring unknown agent: $tok)";;
    esac
  done
fi
sel="$(printf '%s' "$sel" | xargs || true)"
[ -n "$sel" ] || { say "✗ no agents selected — nothing to do."; exit 1; }
say "Agents: $sel"

# --- install shared backend into ~/.tgjobs -------------------------------
head "Installing backend → ${TGJOBS_HOME}"
mkdir -p "$TGJOBS_HOME/jobs/templates/en" "$TGJOBS_HOME/jobs/templates/ru" "$TGJOBS_HOME/telegram"
cp -f "$ROOT"/skill/jobs/*.py "$TGJOBS_HOME/jobs/"
cp -f "$ROOT"/templates/en/*.md "$TGJOBS_HOME/jobs/templates/en/"
cp -f "$ROOT"/templates/ru/*.md "$TGJOBS_HOME/jobs/templates/ru/"
cp -f "$ROOT"/skill/telegram/tg_scan.py "$TGJOBS_HOME/telegram/"
cp -f "$ROOT/VERSION" "$TGJOBS_HOME/VERSION" 2>/dev/null || true
printf 'telegram-intent-scanner\ninstalled_at=%s\n' "$TS" > "$TGJOBS_HOME/.tgjobs-install"
say "backend + templates (en/ru) installed  (v${VER})"

# --- migrate an older ~/.claude product install --------------------------
if [ -f "$HOME/.claude/jobs/.jobscanner" ] && [ ! -f "$TGJOBS_HOME/jobs/config.json" ]; then
  head "Migrating previous install (~/.claude → ~/.tgjobs)"
  for pair in "jobs/config.json:jobs/config.json" "jobs/jobs.db:jobs/jobs.db" \
              "telegram/credentials.env:telegram/credentials.env" "telegram/jobscan.session:telegram/jobscan.session"; do
    src="$HOME/.claude/${pair%%:*}"; dst="$TGJOBS_HOME/${pair##*:}"
    [ -f "$src" ] && { mkdir -p "$(dirname "$dst")"; mv "$src" "$dst"; say "moved ${pair##*:}"; }
  done
fi

# --- adapter writers -----------------------------------------------------
BODY="$ROOT/adapters/$LANG_CHOICE"
# localized skill descriptions
if [ "$LANG_CHOICE" = ru ]; then
  DESC_JOBS="Просканировать Telegram-каналы пользователя на новые вакансии по его критериям и записать подходящие в Markdown. Триггеры: /tg-intent, «проверь вакансии»."
  DESC_SETUP="Настроить сканер вакансий Telegram: API-ключ, вход, рабочая папка. Триггер: /tg-intent-setup."
else
  DESC_JOBS="Scan the user's Telegram channels for new job posts matching their Search Criteria and write matches to a Markdown file. Trigger on /tg-intent or 'scan telegram jobs'."
  DESC_SETUP="Set up the Telegram job scanner: API key, login, job folder. Trigger on /tg-intent-setup."
fi

write_skill() { # DIR NAME DESC BODYFILE
  mkdir -p "$1"
  # Quote the YAML scalar: descriptions contain ': ' (and Russian), which is
  # invalid in a plain scalar. Escape backslashes first, then double-quotes.
  local __d="$3"
  __d="${__d//\\/\\\\}"
  __d="${__d//\"/\\\"}"
  { printf -- '---\nname: %s\ndescription: "%s"\n---\n\n' "$2" "$__d"; cat "$4"; } > "$1/SKILL.md"
}
write_gemini_toml() { # OUT DESC BODYFILE
  mkdir -p "$(dirname "$1")"
  { printf 'description = "%s"\nprompt = """\n' "$2"; cat "$3"; printf '\n"""\n'; } > "$1"
}

install_claude() {
  mkdir -p "$HOME/.claude/commands"
  cp -f "$BODY/tg-intent.md"       "$HOME/.claude/commands/tg-intent.md"
  cp -f "$BODY/tg-intent-setup.md" "$HOME/.claude/commands/tg-intent-setup.md"
  say "Claude Code: /tg-intent + /tg-intent-setup → ~/.claude/commands/"
  local res
  res="$(python3 - "$HOME/.claude/settings.json" "$TGJOBS_HOME" <<'PY'
import json, os, sys, pathlib, shutil
f, home = pathlib.Path(sys.argv[1]), sys.argv[2]
hm = os.path.expanduser("~")
tilde = "~" + home[len(hm):] if home.startswith(hm) else home
try:
    data = json.loads(f.read_text()) if f.exists() else {}
except Exception:
    print("skip"); raise SystemExit
if not isinstance(data, dict): data = {}
if f.exists(): shutil.copyfile(f, str(f) + ".tgjobs.bak")
f.parent.mkdir(parents=True, exist_ok=True)
allow = data.setdefault("permissions", {}).setdefault("allow", [])
rules = ["Bash(cat:*)"]
for base in {tilde, home}:  # both ~ and absolute forms so either match style works
    rules += [
        f"Bash(python3 {base}/jobs/scan.py:*)",
        f"Bash(python3 {base}/jobs/config.py:*)",
        f"Bash(python3 {base}/jobs/setup.py:*)",
        f"Bash(python3 {base}/jobs/update.py:*)",
        f"Bash(uv run --with telethon python {base}/telegram/tg_scan.py:*)",
    ]
for r in rules:
    if r not in allow: allow.append(r)
f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
print("merged")
PY
)" || res=skip
  if [ "$res" = merged ]; then
    say "Claude Code: settings.json — /tg-intent commands allow-listed, no prompts (backup .tgjobs.bak)"
  else
    say "Claude Code: couldn't update ~/.claude/settings.json — /tg-intent may ask for permission (harmless)."
  fi
}

_codex_print_block() {
  printf '      approval_policy = "never"\n      sandbox_mode   = "workspace-write"\n      [sandbox_workspace_write]\n      network_access = true\n      writable_roots = ["%s"]\n' "$TGJOBS_HOME"
}

# Safely add the sandbox block to ~/.codex/config.toml. Only edits when neither
# `sandbox_mode` nor `[sandbox_workspace_write]` already exist (to avoid TOML
# duplicate-key/table hazards); prepends top-level keys, appends the table,
# validates the result with tomllib, and backs up. Echoes merged|manual.
_codex_merge() {
  python3 - "$HOME/.codex/config.toml" "$TGJOBS_HOME" <<'PY'
import pathlib, sys, shutil
path, home = pathlib.Path(sys.argv[1]), sys.argv[2]
orig = path.read_text(encoding="utf-8") if path.exists() else ""
if ("sandbox_mode" in orig) or ("sandbox_workspace_write" in orig):
    print("manual"); raise SystemExit
top = []
if "approval_policy" not in orig:
    top.append('approval_policy = "never"')
top.append('sandbox_mode = "workspace-write"')
head = "\n".join(top) + "\n\n"
table = f'[sandbox_workspace_write]\nnetwork_access = true\nwritable_roots = ["{home}"]\n'
body = (orig.rstrip("\n") + "\n\n") if orig.strip() else ""
new = head + body + table
try:  # validate before writing (tomllib is 3.11+; skip check if unavailable)
    import tomllib
    tomllib.loads(new)
except ModuleNotFoundError:
    pass
except Exception:
    print("manual"); raise SystemExit
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    shutil.copyfile(path, str(path) + ".tgjobs.bak")
path.write_text(new, encoding="utf-8")
print("merged")
PY
}

install_codex() {
  for base in "$HOME/.agents/skills" "$HOME/.codex/skills"; do
    write_skill "$base/tg-intent"       tg-intent       "$DESC_JOBS"  "$BODY/tg-intent.md"
    write_skill "$base/tg-intent-setup" tg-intent-setup "$DESC_SETUP" "$BODY/tg-intent-setup.md"
  done
  say "Codex: skills → ~/.agents/skills/ (+ ~/.codex/skills/)"

  # Codex runs shell in a sandbox that (by default) has no network and can't
  # write outside the project — but /tg-intent needs both (Telegram API + ~/.tgjobs).
  local do_write=0 ans=""
  if [ "$ASSUME_YES" -eq 0 ]; then
    say "Codex needs its sandbox widened (enable network + allow writes to ~/.tgjobs)."
    tty_read ans "  Add this to ~/.codex/config.toml automatically (with backup)? [Y/n]: "
    case "$ans" in n|N|no|No|NO) do_write=0;; *) do_write=1;; esac
  fi

  if [ "$do_write" -eq 1 ] && [ "$(_codex_merge)" = merged ]; then
    say "Codex: config.toml updated — network + writable_roots. Backup: ~/.codex/config.toml.tgjobs.bak"
  else
    if [ "$do_write" -eq 1 ]; then
      say "Codex: config.toml already has sandbox settings — didn't touch it. Make sure it has:"
    else
      say "Codex: add this to ~/.codex/config.toml (top-level keys ABOVE any [table]):"
    fi
    _codex_print_block
  fi
}

install_gemini() {
  write_gemini_toml "$HOME/.gemini/commands/tg-intent.toml"       "$DESC_JOBS"  "$BODY/tg-intent.md"
  write_gemini_toml "$HOME/.gemini/commands/tg-intent-setup.toml" "$DESC_SETUP" "$BODY/tg-intent-setup.md"
  say "Gemini: /tg-intent + /tg-intent-setup → ~/.gemini/commands/"
  local res
  res="$(python3 - "$HOME/.gemini/settings.json" "$TGJOBS_HOME" <<'PY'
import json, sys, pathlib, shutil
f, home = pathlib.Path(sys.argv[1]), sys.argv[2]
try:
    data = json.loads(f.read_text()) if f.exists() else {}
except Exception:
    print("skip"); raise SystemExit
if not isinstance(data, dict): data = {}
if f.exists(): shutil.copyfile(f, str(f) + ".tgjobs.bak")
f.parent.mkdir(parents=True, exist_ok=True)
data.setdefault("security", {}).setdefault("folderTrust", {})["enabled"] = True
allowed = data.setdefault("tools", {}).setdefault("allowed", [])
# Directory prefix covers scan.py/config.py/setup.py/update.py in one entry.
for p in (f"run_shell_command(python3 {home}/jobs)", "run_shell_command(cat)"):
    if p not in allowed: allowed.append(p)
f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
print("merged")
PY
)" || res=skip
  if [ "$res" = merged ]; then
    say "Gemini: settings.json — folder trust + shell allowlist merged (backup .tgjobs.bak)"
  else
    say "Gemini: couldn't update ~/.gemini/settings.json — set security.folderTrust.enabled=true and allow 'python3 ${TGJOBS_HOME}/jobs' yourself (nothing was changed)."
  fi
}

install_cursor() {
  write_skill "$HOME/.cursor/skills/tg-intent"       tg-intent       "$DESC_JOBS"  "$BODY/tg-intent.md"
  write_skill "$HOME/.cursor/skills/tg-intent-setup" tg-intent-setup "$DESC_SETUP" "$BODY/tg-intent-setup.md"
  say "Cursor: skills → ~/.cursor/skills/"
  local res
  res="$(python3 - "$HOME/.cursor/permissions.json" "$TGJOBS_HOME" <<'PY'
import json, sys, pathlib, shutil
f, home = pathlib.Path(sys.argv[1]), sys.argv[2]
try:
    data = json.loads(f.read_text()) if f.exists() else {}
except Exception:
    print("skip"); raise SystemExit
if not isinstance(data, dict): data = {}
if f.exists(): shutil.copyfile(f, str(f) + ".tgjobs.bak")
f.parent.mkdir(parents=True, exist_ok=True)
al = data.setdefault("terminalAllowlist", [])
for p in (f"python3 {home}/jobs", f"python3 {home}/telegram", "cat"):
    if p not in al: al.append(p)
f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
print("merged")
PY
)" || res=skip
  if [ "$res" = merged ]; then
    say "Cursor: permissions.json — terminal allowlist merged (backup .tgjobs.bak)"
  else
    say "Cursor: couldn't update ~/.cursor/permissions.json — add 'python3 ${TGJOBS_HOME}/jobs' to terminalAllowlist yourself (nothing was changed)."
  fi
}

# --- remove pre-rename /tgjobs command files (renamed to /tg-intent) -----
# Backend at ~/.tgjobs is unchanged; only the old command/skill files go.
rm -f "$HOME/.claude/commands/tgjobs.md" "$HOME/.claude/commands/tgjobs-setup.md" \
      "$HOME/.gemini/commands/tgjobs.toml" "$HOME/.gemini/commands/tgjobs-setup.toml" 2>/dev/null || true
rm -rf "$HOME/.agents/skills/tgjobs" "$HOME/.agents/skills/tgjobs-setup" \
       "$HOME/.codex/skills/tgjobs" "$HOME/.codex/skills/tgjobs-setup" \
       "$HOME/.cursor/skills/tgjobs" "$HOME/.cursor/skills/tgjobs-setup" 2>/dev/null || true

# --- install selected agents --------------------------------------------
for a in $sel; do
  head "Agent: $a"
  install_"$a"
done

# --- record what's installed (agents accumulate across runs) -------------
# `installed.json` is the source of truth for `--update`: it lists every agent
# the skill lives in so one update refreshes them all.
python3 - "$TGJOBS_HOME/installed.json" "$LANG_CHOICE" "$VER" "$TS" $sel <<'PY'
import json, sys, pathlib
f = pathlib.Path(sys.argv[1]); lang, ver, ts = sys.argv[2], sys.argv[3], sys.argv[4]
new = sys.argv[5:]
try:
    d = json.loads(f.read_text()) if f.exists() else {}
except Exception:
    d = {}
if not isinstance(d, dict): d = {}
agents = d.get("agents") if isinstance(d.get("agents"), list) else []
for a in new:
    if a not in agents: agents.append(a)
d.update({"agents": agents, "lang": lang, "version": ver, "updated_at": ts})
f.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
PY

head "Done"
say "Backend: ${TGJOBS_HOME}  (v${VER}, language: ${LANG_CHOICE})"
if [ "$DO_UPDATE" -eq 1 ]; then
  say "Updated: $sel"
else
  say "Next: open one of the agents above and run  /tg-intent-setup"
  say "Re-run any time to add another agent; /tg-intent will offer updates when available."
fi
