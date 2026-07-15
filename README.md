# Telegram Job Scanner

A [Claude Code](https://claude.com/claude-code) skill that scans the Telegram
channels **you** already follow, keeps only the vacancies that match what
you're looking for, and writes them to a tidy Markdown file — on demand, with
one command: `/tgjobs`.

The matching is done by Claude itself, right inside your Claude Code session.
**There's no AI API key to buy and no server to run** — the only credential you
need is a free personal Telegram API key.

---

## What it does

```
/tgjobs
  → reads your channel list        (Telegram Sources.md)
  → fetches new posts since last run (per-channel cursor, nothing re-fetched)
  → for each posting, Claude decides: is this a real job? does it match you?
  → writes the matches               (matches+2026-07-13_1430.md)
```

You control two plain-text files:

| File | What it's for |
|------|---------------|
| `Search Criteria.md`  | What you're looking for, in plain language. Edit it to change what `/tgjobs` keeps. |
| `Telegram Sources.md` | Which channels/groups to scan, one per line. |

Both live in a folder you choose (e.g. `~/job-hunt`), so you can read the
results in any editor, Obsidian, Finder — whatever.

## Requirements

- **Claude Code** (this is a skill for it).
- **[uv](https://astral.sh/uv)** — runs the Telegram library in an isolated
  env, no system Python installs. Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A **Telegram account** that is a member of the channels you want to scan.

## Install

**The easy way — one command, no cloning, nothing to build.** Paste this into
your terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/xcvmxc/telegram-job/main/install.sh | bash
```

It downloads the skill and copies it into `~/.claude/`.

<details>
<summary>Prefer to clone the repo instead?</summary>

```bash
git clone https://github.com/xcvmxc/telegram-job.git
cd telegram-job
./install.sh
```
</details>

The installer backs up anything it overwrites; your `jobs.db` and `config.json`
are never touched. Then, in Claude Code:

```
/tgjobs-setup
```

The wizard walks you through three things:

1. **Telegram API key** — create one for free at
   [my.telegram.org](https://my.telegram.org) → *API development tools*
   (takes ~1 minute). You paste the `api_id` and `api_hash`.
2. **Log in** — a one-time Telegram login (you type the code it texts you).
3. **Job folder** — pick where your files and results live; the wizard drops
   `Search Criteria.md` and `Telegram Sources.md` there for you to edit.

## Use it

1. Edit **`Search Criteria.md`** — describe the roles you want.
2. Edit **`Telegram Sources.md`** — add your channels (one per line). For
   **private** channels, join the invite link in Telegram first, then add it.
   List every channel your account is in with:
   ```bash
   uv run --with telethon python ~/.claude/telegram/tg_scan.py list
   ```
3. Run **`/tgjobs`**. Read the `matches+...md` file it writes.

Run `/tgjobs` whenever you like — it only ever looks at posts newer than the
last run, so repeats are cheap and never duplicate.

### Changing what you search for

Just edit `Search Criteria.md` and run `/tgjobs` again. Nothing else — no
re-setup, no commands. Same for sources: edit `Telegram Sources.md`.

## How it's put together

```
~/.claude/
  commands/tgjobs.md          the /tgjobs pipeline (Claude orchestrates)
  commands/tgjobs-setup.md    the setup wizard
  jobs/
    config.py               resolves your folder + file paths
    db.py                   SQLite schema + URL dedup
    scan.py                 pull / unclassified / save / emit
    setup.py                setup helpers (check / save-creds / init / status)
    jobs.db                 state (cursors, seen posts, matched jobs)
    config.json             { "folder": "..." }
    templates/              the two files scaffolded into your folder
  telegram/
    tg_scan.py              Telethon fetcher (raw messages → JSON)
    credentials.env         your TG_API_ID / TG_API_HASH
    jobscan.session         your Telegram login session
```

## A note on Telegram's terms

This tool reads channels through your own user account (via
[Telethon](https://docs.telethon.dev/)), the same content you can already see
in the app. Automating a user account is a grey area under Telegram's Terms of
Service and, used aggressively, can get an account limited or banned. Scan at a
human pace, only channels you're a member of, and use it at your own risk.

## Uninstall

```bash
rm -rf ~/.claude/jobs ~/.claude/telegram/tg_scan.py \
       ~/.claude/telegram/credentials.env ~/.claude/telegram/jobscan.session \
       ~/.claude/commands/tgjobs.md ~/.claude/commands/tgjobs-setup.md
```

Your job folder (criteria, sources, results) is left alone — delete it yourself
if you want.

## License

[MIT](LICENSE) — use it, fork it, ship it.
