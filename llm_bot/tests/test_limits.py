"""Guardrails: daily limit, per-user concurrency, spend cap + alert-once."""

from shared import limits
from shared.config import settings
from shared.limits import Guardrails, InMemoryCounters


def make():
    return Guardrails(counters=InMemoryCounters())


def test_daily_question_limit():
    g = make()
    for _ in range(settings.per_user_daily_limit):
        assert g.allow_question("U1")
    assert not g.allow_question("U1")
    assert g.allow_question("U2")  # independent per user


def test_user_concurrency_lock():
    g = make()
    assert g.acquire_user("U1")
    assert not g.acquire_user("U1")
    g.release_user("U1")
    assert g.acquire_user("U1")


def test_spend_cap_and_single_alert():
    g = make()
    assert not g.over_budget()
    # far past the cap: 20 USD default
    g.add_spend(input_tokens=5_000_000, output_tokens=1_000_000)
    assert g.over_budget()
    assert g.should_alert_admins()  # first crossing alerts
    assert not g.should_alert_admins()  # only once per day


def test_spend_arithmetic():
    g = make()
    total = g.add_spend(input_tokens=1_000_000, output_tokens=0)
    assert abs(total - limits.PRICES["input_per_mtok"]) < 1e-9


def test_worker_busy_path(monkeypatch):
    import worker.app as worker_app
    from worker.jobs import InMemoryJobStore

    delivered = []
    monkeypatch.setattr(worker_app, "job_store", InMemoryJobStore())
    monkeypatch.setattr(worker_app, "guardrails", make())
    monkeypatch.setattr(
        worker_app.slack_out,
        "deliver",
        lambda channel, ts, text: delivered.append(text),
    )
    monkeypatch.setattr(worker_app, "process", lambda payload: "answer")
    client = worker_app.flask_app.test_client()

    payload = {
        "job_id": "j1",
        "user_id": "U1",
        "channel_id": "D1",
        "placeholder_ts": "1.2",
        "text": "q",
    }
    # simulate U1 already being served
    worker_app.guardrails.acquire_user("U1")
    resp = client.post("/task", json=payload)
    assert resp.status_code == 200 and resp.get_json()["busy"]
    assert delivered == [limits.BUSY_REPLY]

    worker_app.guardrails.release_user("U1")
    assert client.post("/task", json=dict(payload, job_id="j2")).status_code == 204
    assert delivered[-1] == "answer"
