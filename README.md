# Telegram Job Scanner

A skill for AI coding agents that scans the Telegram channels **you already
follow**, keeps only the vacancies matching what you're looking for, and writes
them to a tidy Markdown file — on demand, with one command: `/tgjobs`.

The matching is done by the agent itself, right inside your session.
**There's no AI API key to buy and no server to run** — the only credential you
need is a free personal Telegram API key.

**Works with:** Claude Code · OpenAI Codex · Gemini CLI · Cursor.
**Languages:** English (default) or Russian — chosen at install.

---

## What it does

```
/tgjobs
  → reads your channel list          (Telegram Sources.md)
  → fetches new posts since last run  (per-channel cursor, nothing re-fetched)
  → for each posting, the agent decides: is this a real job? does it match you?
  → writes the matches                (matches+2026-07-13_1430.md)
```

You control two plain-text files (in your chosen language):

| File | What it's for |
|------|---------------|
| `Search Criteria.md`  | What you're looking for, in plain language. Edit it to change what `/tgjobs` keeps. |
| `Telegram Sources.md` | Which channels/groups to scan, one per line. |

The scanner's backend lives in a shared, agent-neutral home (`~/.tgjobs`), so
every agent you install it into uses the same channels, criteria and history.

## Requirements

- One or more of: **Claude Code**, **OpenAI Codex**, **Gemini CLI**, **Cursor**.
- **[uv](https://astral.sh/uv)** — runs the Telegram library in an isolated env.
  Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A **Telegram account** that is a member of the channels you want to scan.

## Install

**One command, no cloning.** It asks which language and which agent(s) to set
up, then installs:

```bash
curl -fsSL https://raw.githubusercontent.com/xcvmxc/telegram-job/main/install.sh | bash
```

Prefer non-interactive? Pass flags (re-run any time to add another agent):

```bash
curl -fsSL .../install.sh | bash -s -- --lang en --agent claude,codex
# --lang en|ru   --agent claude|codex|gemini|cursor|all (comma-separated)
```

<details><summary>From a clone</summary>

```bash
git clone https://github.com/xcvmxc/telegram-job.git && cd telegram-job
./install.sh                 # interactive
./install.sh --lang ru --agent all
```
</details>

The installer never touches your state (`~/.tgjobs/jobs/jobs.db`) or config, and
backs up any agent config it merges into. **Codex** needs one manual line in
`~/.codex/config.toml` (the installer prints it) so `/tgjobs` may reach the
network and write outside the project — this is Codex's sandbox, by design.

Then, in your agent, run **`/tgjobs-setup`** — a wizard that walks you through:

1. **Telegram API key** — free, ~1 min at [my.telegram.org](https://my.telegram.org) → *API development tools*.
2. **Log in** — a one-time Telegram login.
3. **Job folder** — where your files and results live; the two editable files
   are scaffolded there in your chosen language.

## Use it

1. Edit **`Search Criteria.md`** — describe the roles you want.
2. Edit **`Telegram Sources.md`** — add your channels (one per line). For
   **private** channels, join the invite link first, then add it. List every
   channel your account is in with:
   ```bash
   uv run --with telethon python ~/.tgjobs/telegram/tg_scan.py list
   ```
3. Run **`/tgjobs`**. Read the `matches+...md` file it writes.

Run `/tgjobs` whenever you like — it only looks at posts newer than the last
run, from any agent, so repeats are cheap and never duplicate.

**To change what you search for:** edit `Search Criteria.md`. **Sources:** edit
`Telegram Sources.md`. Nothing else — no re-setup.

## Language

Choose English or Russian at install. It sets the conversation language, the
wording of the two editable files, and the wording of the output file. To switch
later, re-run the installer with the other `--lang`.

## Updating

`/tgjobs` checks for a newer version at the end of a run (at most once a day) and
**offers** to update — you just confirm. One update refreshes the shared backend
and **every agent** the skill is installed in, at once, keeping all your state.
You can also update on demand:

```bash
curl -fsSL https://raw.githubusercontent.com/xcvmxc/telegram-job/main/install.sh | bash -s -- --update
```

## How it's put together

```
~/.tgjobs/                          shared, agent-neutral backend
  jobs/{config,db,scan,setup,update}.py  the pipeline (stdlib Python)
  jobs/jobs.db  jobs/config.json    state + config (never overwritten)
  jobs/templates/{en,ru}/           scaffolded files, per language
  telegram/tg_scan.py               Telethon fetcher
  telegram/credentials.env          your TG_API_ID / TG_API_HASH
  telegram/jobscan.session          your Telegram login session

per agent (thin adapter → points at ~/.tgjobs):
  Claude Code   ~/.claude/commands/tgjobs{,-setup}.md
  Codex         ~/.agents/skills/tgjobs{,-setup}/SKILL.md (+ ~/.codex/skills/)
  Gemini CLI    ~/.gemini/commands/tgjobs{,-setup}.toml   (+ settings.json)
  Cursor        ~/.cursor/skills/tgjobs{,-setup}/SKILL.md (+ permissions.json)
```

## A note on Telegram's terms

This reads channels through your own user account (via
[Telethon](https://docs.telethon.dev/)) — the same content you already see in
the app. Automating a user account is a grey area under Telegram's Terms and,
used aggressively, can get an account limited or banned. Scan at a human pace,
only channels you're a member of, and use it at your own risk.

## Uninstall

```bash
rm -rf ~/.tgjobs \
       ~/.claude/commands/tgjobs*.md \
       ~/.agents/skills/tgjobs* ~/.codex/skills/tgjobs* \
       ~/.gemini/commands/tgjobs*.toml \
       ~/.cursor/skills/tgjobs*
```

Merged agent configs (`~/.gemini/settings.json`, `~/.cursor/permissions.json`,
`~/.codex/config.toml`) keep `.tgjobs.bak` backups; edit them back by hand if
you want the allowlist entries gone. Your job folder is left alone.

## License

[MIT](LICENSE) — use it, fork it, ship it.
