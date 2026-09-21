# Lessons from ISMIR 2025 virtual chairs

Source: [`how-to-organize-ismir/chairs-virtual/NOTE.md`](https://github.com/keunwoochoi/how-to-organize-ismir/blob/main/chairs-virtual/NOTE.md)
(Chin-Yun Yu's recap). This doc maps those lessons onto this repo's actual
state — what's already covered, what's a gap, and what's a one-time human
action outside the codebase.

## Timeline

NOTE.md's suggested schedule: miniconf site setup starts ~3 months out;
Slack channel setup 3–4 weeks out; tutorial-attendee Slack invites and
conference-attendee invites as separate milestones about a week apart.

- **Gap**: nothing in this repo encodes a timeline. Worth deciding actual
  2026 dates and writing them into `config.yml` / a planning doc once known
  (`LLM_plan.md` already flags 2026 dates as TBD).
- Registration-rate data point from 2025: ~72% registered 1 month out, ~84%
  at 2 weeks, ~93% at 1 week. Useful for deciding when to send the Slack
  invite email (send too early → most links wasted on people not yet
  registered).

## Miniconf website hosting & deployment

- **Gap vs. NOTE.md's recommended flow.** NOTE.md describes GitHub Actions
  pulling the Sheet on a schedule/trigger and auto-redeploying, so last-minute
  author edits (materials, links) go live without a chair running anything
  locally. This repo does that: `python pull_from_google_sheet.py`
  pulls the Sheet → `sitedata/*.csv`, then `uv run python main.py --build` builds. The github workflow refresh-website.yml chains these two steps and further pushes to Github Pages. 
- **Custom domain**: NOTE.md flags requesting `ismir20xxprogram.ismir.net`
  from the ISMIR Tech Lead and pointing DNS at GitHub Pages — a one-time
  human action, not code. `docs/workflow.md` already hardcodes
  `ismir20xxprogram.ismir.net` as the production URL in
  `modules/papers.py:setSlackChannelDescription`, so this DNS/domain request
  needs to happen before that URL resolves.
- **GitHub Education Pack** for private-repo Pages (data privacy) — human
  action, worth doing early if not already on the org.

## Confidentiality / privacy

- **Already handled**: `remove-author-email` action in `miniconf_prep.py`
  strips private contact info before publishing, matching NOTE.md's
  "avoid committing sensitive data" principle. `LLM_plan.md` also already
  flags stripping `author_emails`/`primary_email`/reviews/`meta_review` from
  the assistant catalogue export.
- NOTE.md's other practice — store spreadsheet credentials as repo secrets,
  not in code — should hold for whatever pulls the Sheet in CI (see gap
  above); confirm the data-pull command's credential source is secrets-based if it
  ever runs in Actions rather than locally.

## Slack: inviting attendees

Two structural issues NOTE.md hit, neither fixable in code, both worth
planning around:

1. **Invite link cap**: a single Slack invite link maxes out at 400 uses,
   below ISMIR's ~600–700 attendees, and the next batch can't be sent until
   the previous batch is mostly accepted. → send the first batch **early**
   (NOTE.md suggests ~1 month out) to leave room for a second batch.
2. **Email mismatch**: attendees often join Slack with a different email
   than they registered with, breaking channel-invite matching
   (`utils/slack.py:inviteUserToChannel` resolves by email and silently
   skips unmatched addresses — this repo already logs/skips rather than
   failing, which is the right behavior, but doesn't solve the mismatch).
   → put a reminder in the invite email to join with the registration
   email; no code fix available.

**Recommended process NOTE.md landed on for tutorials** (documented
operationally in `docs/SLACK.md` and split into staged CLI actions;
default-channel and visibility changes remain workspace-admin console steps
on non-Enterprise plans):

1. Create tutorial channels as public, add them to Slack's **default
   channels** list (auto-joins new members), and keep restricted links out
   during this public phase.
2. Send tutorial-attendee invite email.
3. Once enough tutorial attendees have joined, remove tutorial channels from
   the default list, audit membership, and convert them to private.
4. Verify privacy, publish restricted tutorial links, then send the general
   conference-attendee invite email.

This avoids the manual "hunt down which attendee is which Slack user" work
NOTE.md describes as peaking on tutorial days. Slack permits only public
channels as defaults; converting public channels to private is available in
the UI on all plans, while the conversion API is Enterprise-only.

## Live streaming

Handled by the local host team + YouTube embeds in 2025, not a virtual-chair
or repo concern. No action here.

## Process lessons (org-level, not code)

From NOTE.md's "final thoughts," worth keeping in mind for anyone
coordinating chairs on this repo:

- Front-load prep; the conference week itself has no slack (pun intended)
  for new setup work.
- Avoid duplicate sources of truth — this repo already does this correctly
  by making `sitedata/` (sourced from the Sheet) the single source for both
  the site and Slack automation (`docs/workflow.md` Part 2–3).
- Keep work visible to other chairs by default ("garage door up") rather
  than sharing only on request.
- NOTE.md suggests merging the virtual-chair and web-chair roles next time,
  since the schedule/paper data is copied between the two sites anyway —
  an org decision, not something this repo can enforce.
