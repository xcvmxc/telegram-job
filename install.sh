#!/usr/bin/env bash
#
# Installer for the Telegram job scanner (a Claude Code skill).
#
# Copies the /tgjobs + /tgjobs-setup commands and their Python backend into
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

say() { printf '  %s\n' "$1"; }

# --- prerequisites -------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  say "⚠  'uv' is not installed — install it first, then re-run:"
  say "     curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

# --- locate the product files --------------------------------------------
# Install from a local checkout if this script sits next to the repo files;
# otherwise (piped through `curl | bash`) fetch the repo tarball.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "${SELF_DIR}" ] && [ -f "${SELF_DIR}/skill/commands/tgjobs.md" ]; then
  ROOT="${SELF_DIR}"
else
  for tool in curl tar; do
    command -v "$tool" >/dev/null 2>&1 || { say "✗ '$tool' is required but not installed."; exit 1; }
  done
  say "Downloading…"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  if ! curl -fsSL "$TARBALL" | tar -xz -C "$TMP"; then
    say "✗ download failed — check your connection or install manually (see README)."
    exit 1
  fi
  ROOT="$(cd "$TMP"/*/ && pwd)"
fi

mkdir -p "${CLAUDE}/commands" "${CLAUDE}/jobs/templates" "${CLAUDE}/telegram"

# Back up DEST (if it exists and differs), then copy SRC -> DEST. Silent: the
# per-file detail is noise; the summary at the end is what matters.
install_file() {
  local src="$1" dest="$2"
  if [ -f "$dest" ] && ! cmp -s "$src" "$dest"; then
    local rel="${dest#"${CLAUDE}"/}"
    mkdir -p "${BACKUP}/$(dirname "$rel")"
    cp -p "$dest" "${BACKUP}/${rel}"
  fi
  # -f: overwrite even a read-only dest instead of aborting under `set -e`.
  cp -pf "$src" "$dest"
}

say "Installing…"
install_file "${ROOT}/skill/commands/tgjobs.md"        "${CLAUDE}/commands/tgjobs.md"
install_file "${ROOT}/skill/commands/tgjobs-setup.md"  "${CLAUDE}/commands/tgjobs-setup.md"
for f in config.py db.py scan.py setup.py; do
  install_file "${ROOT}/skill/jobs/${f}" "${CLAUDE}/jobs/${f}"
done
install_file "${ROOT}/templates/Search Criteria.md"  "${CLAUDE}/jobs/templates/Search Criteria.md"
install_file "${ROOT}/templates/Telegram Sources.md" "${CLAUDE}/jobs/templates/Telegram Sources.md"
install_file "${ROOT}/skill/telegram/tg_scan.py" "${CLAUDE}/telegram/tg_scan.py"

# Marker so future installs / uninstall can recognise this install.
printf 'telegram-job-scanner\ninstalled_at=%s\n' "$TS" > "${CLAUDE}/jobs/.jobscanner"

[ -d "$BACKUP" ] && say "(backed up previous version → ${BACKUP})"

say "✓ Installed. Open Claude Code and run  /tgjobs-setup"
