# bot/ — ISMIR Guide (always-on assistant)

LLM-powered Slack assistant for ISMIR 2026 (see `../LLM_plan.md`). Own uv
project on Python 3.12+ — never imports root modules; the only input is the
catalogue the export stage uploads (`../catalogue/`).

Two Cloud Run services:

- **ingress/** — public. Verifies the Slack signature, runs deterministic
  pre-checks, posts a "Searching…" placeholder, enqueues a Cloud Task.
  Nothing slow happens here (Slack's 3 s ack window).
- **worker/** — private (OIDC from Cloud Tasks only). Idempotency check,
  scope gate, retrieval + agent loop, grounding, then `chat.update`s the
  placeholder. Currently a stubbed echo agent (milestone 2).

## Dev

```bash
cd bot
uv sync
uv run pytest
```

Local loop without GCP (`LOCAL_MODE=1` = direct HTTP enqueue + in-memory
job store):

```bash
LOCAL_MODE=1 SLACK_BOT_TOKEN=xoxb-... uv run python -m worker.app   # :8081
LOCAL_MODE=1 WORKER_URL=http://localhost:8081 SLACK_BOT_TOKEN=xoxb-... \
    SLACK_SIGNING_SECRET=... uv run python -m ingress.app           # :8080
# expose :8080 with e.g. `ngrok http 8080` and point the Slack app at it
```

`CATALOGUE_DIR=/path/to/build/catalogue_mock` (milestone 3) reads local
artifacts instead of GCS — pairs with the mock pipeline in `../catalogue/`.

## Slack app registration (one-time)

1. Create the app from `slack-app-manifest.yml` in the ISMIR 2026 workspace
   (separate from the provisioning app in `docs/SLACK.md`).
2. Install to workspace; put the bot token + signing secret in Secret
   Manager (`ismir-guide-slack-bot-token`, `ismir-guide-slack-signing-secret`).
3. Deploy (`../infra/deploy_bot.sh`), then set the manifest's
   `<INGRESS_URL>` placeholders and re-apply the manifest.
4. Enable the Agents/Assistant feature for the DM experience (milestone 4).

## Guardrails

- Per-user daily limit (`PER_USER_DAILY_LIMIT`, default 20) — enforced in
  ingress, before any task or LLM cost. Button clicks don't count.
- Per-user concurrency 1 — worker lock; global concurrency = Cloud Tasks
  queue setting.
- `MAX_DAILY_SPEND_USD` (default 20) — worker accumulates token cost in a
  Firestore counter; over cap → canned "temporarily unavailable" + one DM
  to each id in `ADMIN_USER_IDS`.
- Scope-gate eval: `evals/scope_queries.jsonl` (50 labeled queries, incl.
  profanity-legitimate MIR cases) + `evals/run_scope_eval.py` — run with
  real embeddings to tune `SIM_STRONG`/`SIM_WEAK` in `worker/scope_gate.py`.
- Load test: `evals/load_test.py` against a locally running worker.
- Post-conference: delete all profiles 30 days after the event unless
  opted in (one-off operator script against the `profiles` collection).

## Deploy

```bash
PROJECT=<gcp-project> REGION=<region> ../infra/deploy_bot.sh
```

CI (`.github/workflows/bot-deploy.yml`) is path-filtered to `bot/**` and
`infra/**` only — provisioning edits can never redeploy the bot.

`shared/catalogue_schema.py` is vendored from `../catalogue/schema.py` at
build time (single schema definition) — it is gitignored here; don't edit it.
