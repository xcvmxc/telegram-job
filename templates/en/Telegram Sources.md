# Telegram sources to scan
#
# Two sections below: channels under "## Active" are scanned; channels under
# "## Inactive" are kept but skipped. Move a line between them to pause or
# resume a channel without deleting it.
#
# List each channel as a simple bullet, one per line:
#     - @channelname
# A plain line without the "- " works too. Lines starting with "#" are ignored.
#
# ---------------------------------------------------------------------------
# ACCEPTED FORMATS (put any of these after the "- ")
# ---------------------------------------------------------------------------
#   @channelname                 public channel or group (username)
#   https://t.me/channelname     public link — same as @channelname
#   https://t.me/+AbC123xyz      PRIVATE invite link (join it in Telegram first)
#   -1001234567890               numeric id (private channel with no username)
#
# You must be a MEMBER of every channel you list. To see every channel/group
# your account is in — with a ready-to-paste value for each — run:
#   uv run --with telethon python ~/.tgjobs/telegram/tg_scan.py list

## Active
# Delete the examples below and add your channels here, one bullet per line.
# - @example_jobs_channel
# - https://t.me/another_public_jobs_channel
# - https://t.me/+ExamplePrivateInviteHash
# - -1001234567890


## Inactive
# Channels parked here are NOT scanned. Move a line up to "## Active" to resume.
# - @some_channel_on_hold
