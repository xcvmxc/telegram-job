# What I'm searching for

This file holds one or more **intents**. An intent is a separate search — its
own *look for / exclude / notes* — and **each intent gets its own export file**,
named after it (e.g. `Product Manager+2026-07-16_1830.md`).

Write in plain language. The AI reads this file on every run and files each
matching posting under the intent(s) it fits (a posting can land in more than
one). **To change what you search for, edit this file and run `/tg-intent`
again.** No commands, no re-setup.

Add as many intents as you like — copy an `## Intent:` block and rename it.
Delete the examples below and describe your own.

---

## Intent: Product Manager

**Look for:** Product Manager, Senior PM, Product Owner — mid to senior.

**Exclude:** project / program / delivery management, scrum masters, pure sales,
account management, support. No junior roles or internships.

**Notes:** individual-contributor and lead product roles. When you're unsure but
it's plausibly relevant, keep it.

---

## Intent: Data & Analytics

**Look for:** Data Analyst, Analytics Engineer, BI — SQL-heavy roles.

**Exclude:** data entry, pure ML research, unpaid or equity-only.

**Notes:** remote or EU time zones preferred.

---

### How it works

- **One file per intent.** Each `## Intent:` above produces its own
  `<name>+<timestamp>.md`. If you delete every `## Intent:` header, the whole
  file becomes a single default search (output: `matches+<timestamp>.md`).
- **Links and posts.** A matching role with an application link is surfaced as
  that link; a fitting post with no link is surfaced as the post itself (with a
  short excerpt).
- **Renaming an intent** starts a fresh one — its recent-duplicate history
  resets, so you may see a role reappear once within the next couple of days.
