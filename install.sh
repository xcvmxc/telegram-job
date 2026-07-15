#!/usr/bin/env bash
#
# Установщик сканера вакансий в Telegram (скилл для Claude Code).
#
# Копирует команды /tgjobs + /tgjobs-setup и их Python-бэкенд в ~/.claude.
# Существующие файлы сначала бэкапятся; ваше состояние (jobs.db) и конфиг
# (config.json) не трогаются.
#
# Проще всего (без клонирования):
#   curl -fsSL https://raw.githubusercontent.com/xcvmxc/telegram-job/main/install.sh | bash
#
# Или из локальной копии:
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

# --- пререквизиты --------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  say "⚠  'uv' не установлен — установите его, затем запустите заново:"
  say "     curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

# --- найти файлы продукта ------------------------------------------------
# Ставим из локальной копии, если скрипт лежит рядом с файлами репозитория;
# иначе (запуск через `curl | bash`) скачиваем тарбол репозитория.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "${SELF_DIR}" ] && [ -f "${SELF_DIR}/skill/commands/tgjobs.md" ]; then
  ROOT="${SELF_DIR}"
else
  for tool in curl tar; do
    command -v "$tool" >/dev/null 2>&1 || { say "✗ требуется '$tool', но он не установлен."; exit 1; }
  done
  say "Скачивание…"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  if ! curl -fsSL "$TARBALL" | tar -xz -C "$TMP"; then
    say "✗ не удалось скачать — проверьте соединение или установите вручную (см. README)."
    exit 1
  fi
  ROOT="$(cd "$TMP"/*/ && pwd)"
fi

mkdir -p "${CLAUDE}/commands" "${CLAUDE}/jobs/templates" "${CLAUDE}/telegram"

# Бэкапим DEST (если существует и отличается), затем копируем SRC -> DEST.
# Тихо: детали по каждому файлу — это шум, важна итоговая строка.
install_file() {
  local src="$1" dest="$2"
  if [ -f "$dest" ] && ! cmp -s "$src" "$dest"; then
    local rel="${dest#"${CLAUDE}"/}"
    mkdir -p "${BACKUP}/$(dirname "$rel")"
    cp -p "$dest" "${BACKUP}/${rel}"
  fi
  # -f: перезаписать даже read-only dest, а не падать под `set -e`.
  cp -pf "$src" "$dest"
}

say "Установка…"
install_file "${ROOT}/skill/commands/tgjobs.md"        "${CLAUDE}/commands/tgjobs.md"
install_file "${ROOT}/skill/commands/tgjobs-setup.md"  "${CLAUDE}/commands/tgjobs-setup.md"
for f in config.py db.py scan.py setup.py; do
  install_file "${ROOT}/skill/jobs/${f}" "${CLAUDE}/jobs/${f}"
done
install_file "${ROOT}/templates/Search Criteria.md"  "${CLAUDE}/jobs/templates/Search Criteria.md"
install_file "${ROOT}/templates/Telegram Sources.md" "${CLAUDE}/jobs/templates/Telegram Sources.md"
install_file "${ROOT}/skill/telegram/tg_scan.py" "${CLAUDE}/telegram/tg_scan.py"

# Маркер, чтобы будущие установки / удаление распознавали эту установку.
printf 'telegram-job-scanner\ninstalled_at=%s\n' "$TS" > "${CLAUDE}/jobs/.jobscanner"

[ -d "$BACKUP" ] && say "(предыдущая версия сохранена в резерв → ${BACKUP})"

say "✓ Установлено. Откройте Claude Code и запустите  /tgjobs-setup"
