# Telegram sources to scan
#
# Add ONE channel or group per line. Lines starting with "#" are ignored
# (that's how these instructions stay out of the way). Blank lines are fine.
#
# To change which channels are scanned, just edit this list and run /jobs again.
#
# ---------------------------------------------------------------------------
# ACCEPTED FORMATS
# ---------------------------------------------------------------------------
#   @channelname                 public channel or group (username)
#   https://t.me/channelname     public link — same as @channelname
#   https://t.me/+AbC123xyz      PRIVATE invite link (join it first, see below)
#   -1001234567890               numeric id (private channel with no username)
#
# ---------------------------------------------------------------------------
# IMPORTANT: you must be a MEMBER of every channel/group you list
# ---------------------------------------------------------------------------
# The scanner reads channels through YOUR Telegram account — the same way you
# read them in the app. So for each source:
#
#   * Public channel  -> just add its @handle below.
#   * Private channel -> open its invite link in Telegram and JOIN it first,
#                        then add the invite link (or its numeric id) below.
#
# To see every channel/group your account is in — with a ready-to-paste value
# for each — run this in your terminal:
#
#   uv run --with telethon python ~/.claude/telegram/tg_scan.py list
#
# ---------------------------------------------------------------------------
# EXAMPLES (these are placeholders — delete them and add your real channels)
# ---------------------------------------------------------------------------
# @example_jobs_channel
# https://t.me/another_public_jobs_channel
# https://t.me/+ExamplePrivateInviteHash
# -1001234567890

# ↓↓↓  add your channels below this line  ↓↓↓
