# Responsibility matrix: presentation assets (PDF / poster / slides / video)

Who owns collecting/publishing each presentation asset, cross-referencing the
[how-to-organize-ismir](https://github.com/keunwoochoi/how-to-organize-ismir)
chair guides against how this repo actually models the data
(`docs/SPREADSHEET_FORMAT.md`, `docs/MOCKUP.md`). ISMIR 2025 (the guides'
basis) was **in-person**; ISMIR 2026 is **mostly virtual** — noted per row
where that changes who can plausibly own the work.

| Asset | 2025 (in-person) owner | Carries over to 2026 (virtual)? | Source |
|---|---|---|---|
| Camera-ready paper PDF, proceedings compile | **Publication Chairs** — full CMT export → LaTeX → Zenodo pipeline | Yes, unaffected by venue | `chairs-publication/PROCEEDINGS.md` |
| Poster PDF, slides PDF, pre-recorded talk video | **Authors** upload (chased by Publication Chairs as "author liaison": reminders via CMT queries, deadline) | Yes — this repo already models these as author-supplied Drive links pasted into the `papers` sheet tab, filled independent of venue | `chairs-publication/README.md` (deliverables/reminders); this repo's `docs/SPREADSHEET_FORMAT.md:15` + `docs/MOCKUP.md:17` (`raw_pdf_path`/`raw_video`/`raw_poster_pdf`/`raw_slides_pdf`) |
| LBD poster / thumbnail / demo video | **LBD Chairs** — spec + camera-ready collection | Yes, unaffected by venue (LBD chairs own the spec regardless of in-person/virtual delivery) | `chairs-lbd/README.md:56-59,88` |
| Live-session recording | N/A by design — **live Zoom sessions are not recorded** | Resolved (see below) | Decision, 2026-07-20 |

## Resolved: no live-session capture needed

2025's model split **policy** (virtual chairs: consent, archiving, on-demand
access) from **capture** (local venue AV team: actually hitting record). 2026
has no physical venue, so that capture role has no obvious owner — but it
turns out it doesn't need one:

**Decision:** each presentation is **pre-recorded** by the author (the
existing `raw_video`/`video` column in the `papers` sheet tab — already
modeled in `docs/SPREADSHEET_FORMAT.md` and `docs/MOCKUP.md`) and is *also*
delivered **live** via Zoom for real-time Q&A/discussion. The live Zoom
session itself is **not recorded**. The permanent on-demand asset for every
paper is the author-supplied pre-recorded video, not a capture of the live
call.

Consequences:
- No gap to fill — Publication Chairs already own chasing authors for the
  pre-recorded video (same as PDF/poster/slides), and no new "who hits
  record" role or download/publish pipeline is needed.
- `chairs-virtual/README.md`'s "archiving recordings" / "recording and
  sharing consent" duties don't apply to live sessions for 2026 — there's
  nothing captured to archive or consent to.
- `docs/ZOOM.md` needs no recording-related feature (no `auto_recording`
  setting, no post-session download step) — confirmed intentionally out of
  scope, not an oversight.
- Worth stating explicitly in author-facing instructions (Presenter & Author
  Instructions page, owned by Publication Chairs per
  `chairs-publication/README.md`) that **the live session will not be
  recorded**, so authors know their pre-recorded upload is the only
  permanent record of their talk.
