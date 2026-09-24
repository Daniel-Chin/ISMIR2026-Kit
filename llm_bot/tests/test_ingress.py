"""Ingress logic tests: pre-checks and dispatch payload shape.

Signature verification is Bolt's, not ours — we test our handlers' logic
by calling them directly with a fake client/queue.
"""

import os

os.environ["LOCAL_MODE"] = "1"

from ingress import app as ingress_app  # noqa: E402


class FakeClient:
    def __init__(self):
        self.posted = []

    def chat_postMessage(self, **kwargs):
        self.posted.append(kwargs)
        return {"channel": kwargs["channel"], "ts": "111.222"}


class FakeQueue:
    def __init__(self):
        self.items = []

    def enqueue(self, payload):
        self.items.append(payload)


def test_precheck_rejects():
    assert ingress_app._precheck("x" * 3000, False) == ingress_app.TOO_LONG
    assert ingress_app._precheck("hi", True) == ingress_app.NO_FILES
    assert ingress_app._precheck("   ", False) is not None
    assert ingress_app._precheck("beat tracking papers?", False) is None


def test_dispatch_payload(monkeypatch):
    fake_queue = FakeQueue()
    monkeypatch.setattr(ingress_app, "queue", fake_queue)
    client = FakeClient()

    ingress_app._dispatch(
        client,
        job_id="Ev42",
        user_id="U1",
        channel_id="D1",
        thread_ts="123.456",
        text="who wrote the SDTW paper?",
        source="dm",
    )

    assert client.posted[0]["text"] == ingress_app.PLACEHOLDER
    assert len(fake_queue.items) == 1
    payload = fake_queue.items[0]
    assert payload["job_id"] == "Ev42"
    assert payload["placeholder_ts"] == "111.222"
    assert payload["channel_id"] == "D1"
    assert payload["source"] == "dm"
