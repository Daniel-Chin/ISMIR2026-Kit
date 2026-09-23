"""Worker endpoint tests: idempotency, malformed tasks, failure retry path."""

import os

os.environ["LOCAL_MODE"] = "1"

import pytest  # noqa: E402

from worker import app as worker_app  # noqa: E402
from worker.jobs import InMemoryJobStore  # noqa: E402

PAYLOAD = {
    "job_id": "Ev123",
    "user_id": "U1",
    "channel_id": "D1",
    "thread_ts": None,
    "placeholder_ts": "1700000000.000100",
    "text": "papers about beat tracking?",
    "source": "dm",
}


@pytest.fixture()
def client(monkeypatch):
    delivered = []
    monkeypatch.setattr(worker_app, "job_store", InMemoryJobStore())
    # These tests cover the task plumbing, not the agent: stub the pipeline
    monkeypatch.setattr(
        worker_app, "process", lambda payload: "echo: " + payload["text"]
    )
    monkeypatch.setattr(
        worker_app.slack_out,
        "deliver",
        lambda channel, ts, text: delivered.append((channel, ts, text)),
    )
    test_client = worker_app.flask_app.test_client()
    test_client.delivered = delivered
    return test_client


def test_answers_once(client):
    resp = client.post("/task", json=PAYLOAD)
    assert resp.status_code == 204
    assert len(client.delivered) == 1
    channel, ts, text = client.delivered[0]
    assert channel == "D1" and ts == PAYLOAD["placeholder_ts"]
    assert "beat tracking" in text  # echo agent


def test_duplicate_delivery_one_answer(client):
    assert client.post("/task", json=PAYLOAD).status_code == 204
    resp = client.post("/task", json=PAYLOAD)
    assert resp.status_code == 200
    assert resp.get_json()["duplicate"] is True
    assert len(client.delivered) == 1


def test_malformed_task_dropped_not_retried(client):
    resp = client.post("/task", json={"job_id": "x"})
    assert resp.status_code == 200  # 2xx: Cloud Tasks must NOT retry
    assert resp.get_json()["dropped"] is True
    assert client.delivered == []


def test_failure_releases_claim_for_retry(client, monkeypatch):
    calls = {"n": 0}

    def flaky(channel, ts, text):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("slack down")
        client.delivered.append((channel, ts, text))

    monkeypatch.setattr(worker_app.slack_out, "deliver", flaky)
    assert client.post("/task", json=PAYLOAD).status_code == 500  # retryable
    assert client.post("/task", json=PAYLOAD).status_code == 204  # retry succeeds
    assert len(client.delivered) == 1


def test_healthz(client):
    assert client.get("/healthz").status_code == 200
