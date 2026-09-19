# Slack integration

Creates one public Slack channel per paper, LBD, music performance, sponsor,
and tutorial; writes a deep link back into the CSV's `channel_url` column
(which the site's "Slack" button links to); invites participants into their
channels; and sets paper channel metadata. Tutorial channels can be converted
to private manually after the temporary default-channel onboarding window.

## Architecture

```
sitedata/papers.csv ── miniconf_prep.py --action setup-papers-<step>
                              │
                              ▼
                   modules/papers.py (Papers)
                     · generates channel names from session/position/title
                     · orchestrates create → link-writeback → invite → set-desc
                              │
                              ▼
                   utils/slack.py (slack_sdk WebClient, bot token)
                     · channel create / invite / topic+purpose
                     · channel_url written into papers.csv
```

| File | Role |
|---|---|
| `utils/slack.py` | Thin Slack Web API wrapper: channel/user lookups, channel creation, invites, topic/purpose, CSV `channel_url` writeback, rate-limit retry |
| `modules/papers.py` | `Papers`: channel naming (`title2channelID`) and the four paper steps |
| `modules/{lbds,music,industry,tutorials}.py` | Same idea for other content types — see [Non-paper modules](#non-paper-modules) |
| `miniconf_prep.py` | CLI entry point (`--action setup-papers-*`, `setup-event-channels`, `create-event-channels`, `setup-tutorials-*`, `setup-lbd`, `setup-music`, `setup-sponsors`) |

## One-time setup (human, ~10 min)

Slack app creation is browser-only. The person must be able to install apps to
the workspace (workspace admin, or an app-approval flow).

1. Create the workspace if needed (a free workspace is fine for the mock run).
2. Create an app at <https://api.slack.com/apps?new_app=1> ("From scratch",
   pick the workspace).
   - The "app name" will be shown in Slack channels, so use something like "Service Bot".
3. **OAuth & Permissions → Scopes → Bot Token Scopes**, add:
   - `channels:manage` — create public channels, invite, set topic/purpose
   - `channels:read` — list channels
   - `groups:write` + `groups:read` — manage tutorial channels after they are
     converted to private (the bot must already be a member)
   - `users:read` + `users:read.email` — resolve author emails to user IDs
   - `chat:write` — post messages (only `postMessageToASlackChannelAsBot`)
   - `channels:join`
4. **Install App to Workspace** and copy the **Bot User OAuth Token**
   (`xoxb-...`).

   The token must start with `xoxb-`. A token beginning with `xoxe.xoxp-`
   (for example, one shown by the Slack CLI or under app configuration tokens)
   is a different credential and is not the bot token expected by this
   repository. Do not put it in `SLACK_TOKEN`. Return to **OAuth &
   Permissions**, install or reinstall the app, and copy the **Bot User OAuth
   Token** instead.

5. In the repo root, add to `.env` (already gitignored — never commit it):

   ```
   SLACK_TOKEN=xoxb-...
   DUMMY_EMAIL=<your-email-in-that-workspace>   # invite target in non-prod mode
   ZOOM_REDIRECT_ACCESS_TOKEN=<put-random-string-here>
   ```

6. Smoke test (read-only, creates nothing):

   ```bash
   .venv/bin/python -c "from utils import slack; print(len(slack.get_all_channels_data()), 'channels')"
   ```

7. Give a nice profile image to the bot.  

## Running it

```bash
# 1. (optional) regenerate channel names in papers.csv and events.csv from session/position/title
.venv/bin/python miniconf_prep.py --path sitedata_mock --action setup-papers-setup-channels
.venv/bin/python miniconf_prep.py --path sitedata_mock --action setup-event-channels

# 2. create channels, write channel_url back into papers.csv and events.csv
.venv/bin/python miniconf_prep.py --path sitedata_mock --action setup-papers-create-channels
.venv/bin/python miniconf_prep.py --path sitedata_mock --action create-event-channels

# 3. invite authors into their channels (non-prod → invites DUMMY_EMAIL instead)
.venv/bin/python miniconf_prep.py --path sitedata_mock --action setup-papers-invite-authors

# 4. set channel topic + purpose (stream URL, title, authors, program-site URL) for papers and poster sessions
#    Run setup-zoom first: this step requires each poster session's live_url. See ./ZOOM.md
.venv/bin/python miniconf_prep.py --path sitedata_mock --action setup-papers-set-desc

# 5. Use CLI tool to set up channel purpose for other events
#    Run setup-zoom first: this step requires each event's live_url. See ./ZOOM.md
uv run python
import utils.slack as s
s.batch_set_channel_description()
```

Use `--path sitedata` for the real conference data and add `--prod true` for
step 3 to invite the real `author_emails`. Steps 3 and 4 can run in either
order; both require step 2 first.

After scripts, manual setup include: setting the correct channels to be default; setting channel description.

`SLACK_TOKEN` is needed for every step that talks to Slack (2–4). Importing
`utils/slack.py` without a token is safe — the client is built lazily and the
first actual API call just fails with `invalid_auth` — so step 1
(`setup-channels`), which only rewrites the CSV, runs without credentials.

Channel names are sanitized to lowercase letters, numbers, dashes, or
underscores only. 

### What each step does

**`setup-channels`** (local only, no Slack writes): overwrites the
`slack_channel` column for every row as
`p{session}-{position}-{first-3-words-of-title}` via `title2channelID` —
lowercased, punctuation stripped, `&` → `and`, spaces → `-`. Example:
`p2-1-reformulating-soft-dynamic`. Skip this step if the sheet already carries
final channel names.

**`create-channels`**: for every `slack_channel` value not already present in
the workspace (public + private channels the bot can see), creates a public
channel; then writes `https://slack.com/app_redirect?channel=<id>` into the
`channel_url` column for every row whose channel exists. The CSV is rewritten
in place. The `app_redirect` form opens the channel in whatever workspace the
clicking user is signed into, so links keep working if the workspace is
renamed.

**`invite-authors`**: splits each row's `author_emails` on `;`, resolves each
email to a workspace user ID, and invites them to the row's channel (skipping
users already in it). Without `--prod`, every channel gets `DUMMY_EMAIL`
instead. **Emails resolve only for active or pending invited members known to
the workspace** — the Web API cannot invite someone *to the workspace* on a
non-Enterprise plan. Unknown emails are printed and skipped. Send workspace
invites first (Slack admin UI or shared invite link), then run this step; an
author can be assigned to a paper channel while their workspace invitation is
still pending. The email in `author_emails` must exactly match the address used
for the workspace invitation.

**`set-desc`**: updates both poster-session channels and paper channels.
For each paper, it matches `Poster Session - <session>` on the same day in
`events.csv`:

- Poster-session channel purpose is set to the poster-session Zoom URL
  (`live_url`) with explicit breakout-room wording.
- Paper channel topic remains `Paper <uid>: <title>`.
- Paper channel purpose contains title, paper page URL, authors, and an
  in-Slack link to the poster-session channel (not the raw Zoom URL).

If a matching poster session is missing, if `live_url` is empty, or if the
poster-session Slack channel is absent, the action stops with an error and
prints the required prerequisite (`setup-zoom` and/or event channel creation).
The program base URL is `miniconf_url` from config.yml.

## Attendee invitation order and temporary tutorial defaults

The [ISMIR 2025 virtual-chairs retrospective](https://github.com/keunwoochoi/how-to-organize-ismir/blob/main/chairs-virtual/NOTE.md#inviting-tutorial-attendees)
recommends inviting tutorial attendees before the general conference audience
and temporarily making tutorial channels default channels. This reduced
last-minute manual support when registration emails did not match the email
people used to join Slack.

Operational sequence:

1. Create `#social`, `#random`, `#help`, and the tutorial channels as **public**
   channels before sending workspace invitations. Ensure the provisioning bot
   is a member so it retains access after tutorial channels become private.
2. Add `#general`, `#social`, `#random`, `#help`, opening session, and the tutorial channels to Slack's
   **Default Channels** list. The first two are permanent defaults; tutorial
   channels are temporary defaults.
3. Send targeted workspace invitations to tutorial attendees. Tell them to use
   the same email address they used for registration.
4. Monitor pending and accepted invitations and handle email mismatches.
5. Once most tutorial attendees have joined, remove only the tutorial channels
   from the default list. Keep `#general`... as defaults.
6. Audit channel membership, then convert each tutorial channel from public to
   private: **channel name → Settings → Change to a private channel**.
7. Verify that the channels are private, then add restricted materials such as
   Zoom links.
8. Send workspace invitations to the general conference audience.
9. Manually handle late tutorial registrants or assign them with
   `setup-tutorials-invite-attendees` after Slack knows their account.
10. Invite volunteers to Slack.

CLI stages:

```bash
# Stage 1: create permanent onboarding + public tutorial channels, and write
# tutorial channel_url values to events.csv
uv run python miniconf_prep.py \
  --path sitedata/ \
  --action setup-tutorials-create-channels

# Manual: make #general and #help etc. permanent defaults, make tutorial
# channels temporary defaults, then send tutorial workspace invites

# Stage 2: assign active or pending invited attendees to their tutorials
uv run python miniconf_prep.py \
  --path sitedata/ \
  --registration-csv /secure/path/registration.csv \
  --action setup-tutorials-invite-attendees \
  --prod true

# Manual: remove only tutorial defaults, audit membership, convert tutorials
# to private, then send general conference workspace invitations
```

The legacy `setup-tutorials` action runs both CLI stages together and leaves
the channels public. Keep it for mock/backward-compatible runs; use the staged
actions for the real invitation sequence.

Important constraints:

- Slack allows only **public** channels to be defaults. Owners, admins, and
  Channel Managers can convert a public channel to private through the Slack
  UI on all plans, subject to workspace permissions. Remove it from the
  default list before conversion.
- Conversion retains the people already in the channel. It also posts a
  channel message announcing the conversion. Audit membership first because
  anyone who joined during the public phase will keep access.
- Treat the public phase as non-confidential. Do not post private Zoom links or
  restricted tutorial materials until conversion. Files exposed while a
  channel is public may remain publicly accessible even after its visibility
  changes.
- The API for converting channels to private
  (`admin.conversations.convertToPrivate`) is Enterprise-only. On Free, Pro,
  and Business+ workspaces, conversion is a manual owner/admin/Channel Manager
  step.
- The CLI automates public-channel creation, link writeback, and attendee
  assignment. Default-channel settings and public-to-private conversion remain
  manual Slack admin steps. The conversion API is not available to this bot on
  non-Enterprise plans.
- Adding a channel to the default list does not retroactively add existing
  workspace members. Removing it later does not remove people who already
  joined.
- Keep `#general` and `#help` public and default throughout the
  conference. Restrict posting in `#general` through Slack's channel
  posting permissions.
- Do not make every paper channel a default channel. Paper channels are public
  and discoverable; assign authors directly and let attendees join the papers
  they want to discuss.
- Workspace invitations and invite links expire after 30 days. A shared invite
  link supports up to 400 uses, so a full ISMIR audience may need staged
  invitations. The 2025 retrospective recommends starting early.

Slack UI path for owners/admins:
**Workspace name → Tools & settings → Workspace settings → Default Channels**.
See Slack's current documentation for
[default channels](https://slack.com/help/articles/201898998-Set-default-channels-for-new-members),
[channel conversion](https://slack.com/help/articles/213185467-Convert-a-channel-to-private-or-public),
and [workspace invitations](https://slack.com/help/articles/201330256-Invite-new-members-to-your-workspace).

# Announcement Bot
See docstring in ../announcement_bot/announcement_bot.py  
We use the #general channel and we do not have an #announcement channel because the free plan can only limit posting permissions in the #general channel.

## Idempotence and the sheet round-trip

Channels are keyed by **name**. `create-channels` checks `isChannel()` before
creating, so re-running never duplicates. This matters because `migrate.sh` /
`migrate_mock.sh` re-pull the Google Sheet and overwrite `papers.csv` —
including `channel_url`. The recovery is to re-run
`setup-papers-create-channels`: existing channels are found by name and their
URLs backfilled. If the sheet should stay the source of truth, paste the
generated `channel_url` values back into the sheet after the first real run.

Corollary: **channel names are identity**. Rerunning `setup-channels` after a
title or session/position change in the sheet produces a *new* name, and
`create-channels` then creates a second channel; the old one must be archived
by hand. Once channels exist, treat `slack_channel` as frozen.

`invite-authors` and `set-desc` are also safe to re-run: invites skip existing
members, and topic/purpose are simply overwritten.

## utils/slack.py API surface

Importing the module is side-effect free apart from loading `.env`: the
`WebClient` is built with whatever `SLACK_TOKEN` is present (possibly empty),
and the user/channel lookup maps are fetched from the API **on first use**,
then cached for the life of the process. A missing token surfaces as
`invalid_auth` on the first real call, not at import. All wrapped calls retry
on `ratelimited` (2 s sleep, up to 100 tries) via the `retry` helper.

| Function | Notes |
|---|---|
| `createPublicSlackChannels(channels)` | Creates each name in the iterable that doesn't exist yet |
| `createPrivateSlackChannels(csvFile, channelColumnName)` | Private variant, reads names from a CSV column (tutorials). Slack caps channel creation at ~90 per run |
| `loadAllChannelData()` | Invalidates the cached channel maps so the next lookup refetches — call after creating channels, before writing links |
| `addChannelLinksToCSV(csvFile, channelColumnName, newCsvFile=None)` | Writes `app_redirect` links into a `channel_url` column; in place unless `newCsvFile` given |
| `inviteUserToChannel(user_email, channelName)` / `inviteUsersToChannel(user_emails, channelName)` | Skips users already in the channel; prints and skips emails not in the workspace |
| `updateTopicandPurpose(channelName, topic, purpose)` | Used by `set-desc` |
| `isChannel(name)` / `getChannelID(name)` / `getUserID(email)` / `getUserEmail(id)` | Cache lookups, no API call |
| `memberEmailsAlreadyInChannel(channelName)` | Emails of current members (None entries for bots) |
| `postMessageToASlackChannelAsBot(channel, text)` | Bot must be a member of the channel |

The channel and user caches are filled on first lookup and then reused; a
channel created outside the script (or by another process while this one runs)
is invisible until `loadAllChannelData()` invalidates the cache or the process
restarts.

## Slack platform constraints

- **Channel names**: max 80 chars, lowercase letters/numbers/hyphens/underscores
  only. `conversations_create` rejects anything else (`invalid_name`), and
  returns `name_taken` even when the clashing channel is **archived** —
  unarchive or pick a new name.
- **~90 channels per run**: Slack rate-limits bulk channel creation; the
  ISMIR 2022 run needed multiple passes for 100+ channels. The retry helper
  handles `ratelimited` waits, but budget time for a big first run.
- Channel and user listings use cursor pagination with Slack's recommended
  page size of 200.
- Channel assignments require the target to be an active or pending invited
  workspace member (see `invite-authors` above).
- The bot can only see private channels it is a member of; `isChannel` may
  report false for a private channel created by someone else, and creation
  then fails with `name_taken`.

## Non-paper modules

`modules/lbds.py`, `modules/music.py`, `modules/industry.py`, and
`modules/tutorials.py` follow the same create → link-writeback → invite flow
for their CSVs. Tutorials split public-channel creation from registered
attendee assignment so chairs can use the temporary-default workflow before
manually converting channels to private. They were ported to the current
`utils/slack.py` signatures in July 2026 — before that they passed
`slackUtils.client` as a first argument and crashed with `TypeError`. They
now also reload channel data between creation and link-writeback, like
`papers.py`. The papers path remains the most exercised one; the non-paper
actions have not been run against a live workspace since the port, so give
them a mock-workspace pass before a real run. LBD naming:
`lp-{position}-{lastname}` (physical) / `lv-…` (virtual), from
`primary_author`.

## Testing without credentials

Everything up to the first API call works offline: modules import, and
`setup-channels` (pure CSV rewrite) runs with no token at all. Anything that
touches Slack needs a real workspace. The cheapest real test is the mock run
(MOCKUP.md § 2) — a free throwaway
workspace, the 6-row `sitedata_mock/papers.csv`, and non-prod invites going
to `DUMMY_EMAIL`. That exercises create → link-writeback → invite → set-desc
end to end without touching real authors.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `invalid_auth` | `SLACK_TOKEN` missing/empty (`.env` is read relative to the CWD — run from repo root), token revoked, wrong workspace, or app uninstalled |
| Token starts with `xoxe.xoxp-` | wrong credential type — this project requires the app's `xoxb-` **Bot User OAuth Token** from **OAuth & Permissions** after installation |
| `missing_scope` | a bot scope from the setup list wasn't added, or the app wasn't **reinstalled** after adding scopes |
| `name_taken` on create | channel already exists **archived**, or is a private channel the bot can't see |
| `invalid_name` | uppercase/punctuation in `slack_channel` — regenerate with `setup-channels` |
| `User <email> does not exist in the workspace.` | author not yet a workspace member — workspace invites are manual, then re-run `invite-authors` |
| `Rate limit exceeded. Retrying...` loops | expected on bulk runs; Slack caps ~90 channel creations per run |
| `channel_url` empty after `migrate.sh` pull | expected — re-run `setup-papers-create-channels` to backfill |
| `[SSL: CERTIFICATE_VERIFY_FAILED]` | handled — the client pins `certifi`'s CA bundle (`utils/slack.py` top) |
