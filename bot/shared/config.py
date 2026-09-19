"""Environment-driven configuration for both Cloud Run services.

Everything secret (Slack tokens, Anthropic key) is injected by Secret
Manager at deploy time — nothing is read from files in the repo.
"""

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # Slack ("ISMIR Guide" app — separate from the provisioning app)
    slack_bot_token: str = field(default_factory=lambda: _env("SLACK_BOT_TOKEN"))
    slack_signing_secret: str = field(
        default_factory=lambda: _env("SLACK_SIGNING_SECRET")
    )

    # Cloud Tasks (ingress -> worker)
    tasks_queue: str = field(
        # projects/<p>/locations/<l>/queues/<q>
        default_factory=lambda: _env("TASKS_QUEUE")
    )
    tasks_sa_email: str = field(default_factory=lambda: _env("TASKS_SA_EMAIL"))
    worker_url: str = field(default_factory=lambda: _env("WORKER_URL"))

    # Firestore (jobs idempotency, profiles, counters)
    gcp_project: str = field(default_factory=lambda: _env("GCP_PROJECT"))

    # Catalogue artifacts
    catalogue_bucket: str = field(default_factory=lambda: _env("CATALOGUE_BUCKET"))
    # Local dev override: read artifacts from a directory, skip GCS entirely
    catalogue_dir: str = field(default_factory=lambda: _env("CATALOGUE_DIR"))

    # Models chosen at deploy time, not in code (LLM_plan.md section 7)
    agent_model: str = field(
        default_factory=lambda: _env("AGENT_MODEL", "claude-sonnet-5")
    )
    scope_model: str = field(
        default_factory=lambda: _env("SCOPE_MODEL", "claude-haiku-4-5")
    )
    embedding_model: str = field(
        default_factory=lambda: _env("EMBEDDING_MODEL", "voyage-3.5")
    )

    # Guardrails
    max_input_chars: int = 2000
    per_user_daily_limit: int = int(_env("PER_USER_DAILY_LIMIT", "20"))
    max_daily_spend_usd: float = float(_env("MAX_DAILY_SPEND_USD", "20"))

    # Local dev: enqueue = direct HTTP POST to worker, in-memory job store
    local_mode: bool = _env("LOCAL_MODE", "").lower() in ("1", "true", "yes")


settings = Settings()
