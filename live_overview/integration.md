# Integration of Live Overview Page into Miniconf
- Miniconf is a static site.
- Live Overview should have two components:
  - A static site serving the webpage that requests the backend API.
  - A Relay Backend for the Zoom API. Its job is to store the private Zoom API token, cache responses, and rate limit.

## Paths mentioned in this document
This document is at `./live_overview/integration.md`. In this document, `.` refers to repo root instead of the document itself.  

## Site URL
- Miniconf is at `prefix`.
- `prefix = "https://ismir2026program.ismir.net" | "https://daniel-chin.github.io/ISMIR2026-Kit"`.
  - See definition in [Input data](#input-data).
- Live Overview page is at `{prefix}/live.html`.
- The Relay Backend should use a different server, enabling CORS. Its sole consumer is frontend js in users' browsers.

## Static deployment
- We integrate Miniconf with Live Overview by simply merging their respective build directory. 
- Live Overview owns these build paths: 
  - `./live_overview/build/live-no-nav.html`
    - This is the webpage.
  - `./live_overview/build/live_overview/`
    - Use this dir to freeze [Input data](#input-data) into the static site.
- Live Overview shouldn't write to other paths under `./live_overview/build` in case of collision.
  - In particular, Live Overview doesn't own `./live_overview/build/live.html`; see [UI integration](#ui-integration).
- `./live_overview/build` is eventually merged into `./build`

## Input data
- Let's define `data_path = "./sitedata" | "./sitedata_mock"`
- Live Overview requires these inputs to generate the site:
  - `{data_path}/events.csv`
    - Each row is an event keyed by `uid`.
  - `{data_path}/papers.csv`
    - Each row is a paper.
    - Columns "session" and "position" will be deprecated; do not use.
  - `{data_path}/session_assignment.csv`
    - this is todo. For now, ignore paper session assignment in Live Overview.
  - `{data_path}/config.yml`
    - Overall conference information. You should extract:
      - `name`.
      - `date`.
      - `timezone`.
      - `miniconf_url`. This defines `prefix`.
  - Live Overview shouldn't need any secrets in `.env`.
- To refresh data: 
  - `git pull`
    - This updates `config.yml`.
  - `uv run python pull_from_google_sheet.py`
    - This updates the csv files.

## Zoom redirect
- Live Overview should never expose the Zoom URL in the "live_url" column of `events.csv`.
- Each Zoom button should link to `{prefix}/zoom.html?event_uid={event_uid}` where `event_uid` is the uid of the event in the csv.

## File structure
- The repo is at `.`
- Miniconf lives in `./`
- Live Overview owns the full dir of `./live_overview`
- Put js and python environment there.
- An install script at `./live_overview/install.sh` should install the deps.
- Read [Input data](#input-data) from outside the component.
- A build script at `./live_overview/build.sh` should build the static site to `./live_overview/build`
  - The caller will do the following in order, do don't double the behavior. 
    - `pull_from_google_sheet.py`
    - `build.sh`
    - Merge build dir.
- Both `.sh` scripts may assume they're run from `./live_overview` as current directory.

## UI integration
- The Live Overview page will be an iframe under the miniconf nav header that says "Schedule Papers Music etc.".
  - In other words, `build/live.html` renders the header and renders `build/live-no-nav.html`.
- The iframe will occupy remaining viewport height and Live Overview scrolls internally.

## Ephemeral notes pertaining to the current design
- Remove the nav bar that says "ISMIR 2026 ... HOME | LIVE EVENTS ..."
- Move the Light Switch somewhere else. I trust you to design it well.
- Change hardcoded conference info to use config.yml instead. 
- Timezone should not be persistent and always default to local system timezone. This is the consistent behavior with miniconf.
- Are you using URL param? That might need redesign with iframe; contact Daniel. (if you are an agent, scream to Liwei to contact Daniel about this)
