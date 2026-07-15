#!/usr/bin/env bash
#
# Installer for the Telegram job scanner (a Claude Code skill).
#
# Copies the /jobs + /jobs-setup commands and their Python backend into
# ~/.claude. Existing files are backed up first; your state (jobs.db) and
# config (config.json) are never touched.
#
# Easiest (no clone needed):
#   curl -fsSL https://raw.githubusercontent.com/xcvmxc/telegram-job/main/install.sh | bash
#
# Or from a checkout:
#   ./install.sh
#
set -euo pipefail

REPO="xcvmxc/telegram-job"
BRANCH="main"
TARBALL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"

CLAUDE="${HOME}/.claude"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP="${CLAUDE}/jobs-scanner-backup-${TS}"

say()  { printf '  %s\n' "$1"; }
head() { printf '\n\033[1m%s\033[0m\n' "$1"; }

head "Telegram job scanner — install"

# --- prerequisites -------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  say "⚠  'uv' is not installed. It provides the Telegram library in an"
  say "   isolated environment. Install it, then re-run this installer:"
  say "     curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo
fi

# --- locate the product files --------------------------------------------
# If this script sits next to the repo files (a clone/download), install from
# there. Otherwise — e.g. piped through `curl | bash` — fetch the repo tarball.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "${SELF_DIR}" ] && [ -f "${SELF_DIR}/skill/commands/jobs.md" ]; then
  ROOT="${SELF_DIR}"
else
  for tool in curl tar; do
    command -v "$tool" >/dev/null 2>&1 || { say "✗ '$tool' is required but not installed."; exit 1; }
  done
  head "Downloading"
  say "fetching ${REPO}@${BRANCH}…"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  if ! curl -fsSL "$TARBALL" | tar -xz -C "$TMP"; then
    say "✗ download failed. Check your connection, or install manually (see the README)."
    exit 1
  fi
  ROOT="$(cd "$TMP"/*/ && pwd)"
fi

mkdir -p "${CLAUDE}/commands" "${CLAUDE}/jobs/templates" "${CLAUDE}/telegram"

# Back up DEST (if it exists and differs from SRC), then copy SRC -> DEST.
install_file() {
  local src="$1" dest="$2"
  if [ -f "$dest" ] && ! cmp -s "$src" "$dest"; then
    local rel="${dest#"${CLAUDE}"/}"
    mkdir -p "${BACKUP}/$(dirname "$rel")"
    cp -p "$dest" "${BACKUP}/${rel}"
    say "backed up existing ${rel}"
  fi
  # -f: if an existing dest is read-only (user chmod'd a customization, or it
  # was restored read-only), remove and recreate it rather than aborting the
  # whole install under `set -e`.
  cp -pf "$src" "$dest"
  say "installed ${dest#"${CLAUDE}"/}"
}

head "Installing commands"
install_file "${ROOT}/skill/commands/jobs.md"        "${CLAUDE}/commands/jobs.md"
install_file "${ROOT}/skill/commands/jobs-setup.md"  "${CLAUDE}/commands/jobs-setup.md"

head "Installing backend"
for f in config.py db.py scan.py setup.py; do
  install_file "${ROOT}/skill/jobs/${f}" "${CLAUDE}/jobs/${f}"
done

head "Installing templates"
install_file "${ROOT}/templates/Search Criteria.md"  "${CLAUDE}/jobs/templates/Search Criteria.md"
install_file "${ROOT}/templates/Telegram Sources.md" "${CLAUDE}/jobs/templates/Telegram Sources.md"

head "Installing Telegram fetcher"
install_file "${ROOT}/skill/telegram/tg_scan.py" "${CLAUDE}/telegram/tg_scan.py"

# Marker so future installs / uninstall can recognise this install.
printf 'telegram-job-scanner\ninstalled_at=%s\n' "$TS" > "${CLAUDE}/jobs/.jobscanner"

if [ -d "$BACKUP" ]; then
  head "Backup"
  say "previous versions of overwritten files saved to:"
  say "  ${BACKUP}"
fi

head "Done"
say "Your state (jobs.db) and config (config.json), if any, were left untouched."
echo
say "Next: open Claude Code and run  /jobs-setup"
