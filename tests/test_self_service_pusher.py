"""Check dispatch routing and failure reporting without network calls."""
from unittest.mock import Mock

import pytest
import requests
from slack_sdk.socket_mode.request import SocketModeRequest

from long_running_bots import self_service_pusher as bot


@pytest.mark.parametrize("contents", [None, "other=value", "pat=", "pat='   '"])
def test_missing_token_explains_setup(tmp_path, monkeypatch, contents):
    path = tmp_path / "bot.env"
    if contents is not None:
        path.write_text(contents)
    monkeypatch.setattr(bot, "GITHUB_TOKEN_FILE", path)
    monkeypatch.setenv("pat", "must-not-use-environment-token")
    with pytest.raises(SystemExit) as error:
        bot.load_github_token()
    assert str(path) in str(error.value)
    assert "pat=YOUR_TOKEN" in str(error.value)
    assert "self_service_pusher.py:" in str(error.value)


def test_token_from_file(tmp_path, monkeypatch):
    path = tmp_path / "bot.env"
    path.write_text("pat='test-token'\n")
    monkeypatch.setattr(bot, "GITHUB_TOKEN_FILE", path)
    assert bot.load_github_token() == "test-token"


@pytest.mark.parametrize("status,expected", [(200, "queued"), (204, "queued"), (403, "rejected"), (422, "rejected"), (None, "before retrying")])
def test_dispatch_acknowledges_first_and_reports_result(monkeypatch, status, expected):
    client = Mock()
    calls = []

    def post(url, **kwargs):
        client.send_socket_mode_response.assert_called_once()
        calls.append((url, kwargs))
        if len(calls) == 1:
            if status is None:
                raise requests.Timeout()
            return Mock(status_code=status)
        return Mock()

    monkeypatch.setattr(bot.requests, "post", post)
    request = SocketModeRequest(type="slash_commands", envelope_id="env", payload={
        "command": bot.COMMAND, "response_url": "https://example.test/reply",
    })
    bot.handle_request(client, request, github_token="test-token")
    url, kwargs = calls[0]
    assert url == "https://api.github.com/repos/daniel-chin/ismir2026-kit/actions/workflows/refresh-website.yml/dispatches"
    assert kwargs["json"] == {"ref": "main"}
    assert kwargs["headers"]["Authorization"] == "Bearer test-token"
    assert expected in calls[1][1]["json"]["text"]


def test_unrelated_request_only_acknowledged(monkeypatch):
    post = Mock()
    monkeypatch.setattr(bot.requests, "post", post)
    client = Mock()
    bot.handle_request(client, SocketModeRequest(type="events_api", envelope_id="env", payload={}), github_token="test-token")
    client.send_socket_mode_response.assert_called_once()
    post.assert_not_called()


def test_dispatch_starts_monitor_for_exact_run(monkeypatch):
    dispatch = Mock(status_code=200)
    dispatch.json.return_value = {"workflow_run_id": 123}
    post = Mock(side_effect=[dispatch, Mock()])
    thread = Mock()
    monkeypatch.setattr(bot.requests, "post", post)
    monkeypatch.setattr(bot, "Thread", thread)
    request = SocketModeRequest(type="slash_commands", envelope_id="env", payload={
        "command": bot.COMMAND, "response_url": "https://example.test/reply",
    })
    bot.handle_request(Mock(), request, github_token="test-token")
    thread.assert_called_once_with(
        target=bot.monitor_run, args=(123, "https://example.test/reply", "test-token"),
        name="website-refresh-123", daemon=True,
    )
    thread.return_value.start.assert_called_once()
    assert "/actions/runs/123" in post.call_args_list[1].kwargs["json"]["text"]


@pytest.mark.parametrize("conclusion,expected", [
    ("success", "succeeded"), ("failure", "did not succeed (failure)"),
    ("cancelled", "cancelled"), ("timed_out", "did not succeed (timed_out)"),
])
def test_monitor_reports_terminal_result(monkeypatch, conclusion, expected):
    queued = Mock()
    queued.json.return_value = {"status": "in_progress"}
    completed = Mock()
    completed.json.return_value = {"status": "completed", "conclusion": conclusion}
    get = Mock(side_effect=[queued, completed])
    send = Mock()
    monkeypatch.setattr(bot.requests, "get", get)
    monkeypatch.setattr(bot, "send_status", send)
    monkeypatch.setattr(bot, "Event", Mock())
    bot.monitor_run(123, "reply-url", "token")
    assert get.call_count == 2
    assert get.call_args.args[0].endswith("/actions/runs/123")
    send.assert_called_once()
    assert expected in send.call_args.args[1]
    assert "/actions/runs/123" in send.call_args.args[1]


def test_monitor_retries_transient_errors(monkeypatch):
    completed = Mock()
    completed.json.return_value = {"status": "completed", "conclusion": "success"}
    get = Mock(side_effect=[requests.Timeout(), completed])
    send = Mock()
    monkeypatch.setattr(bot.requests, "get", get)
    monkeypatch.setattr(bot, "send_status", send)
    monkeypatch.setattr(bot, "Event", Mock())
    bot.monitor_run(123, "reply-url", "token")
    assert get.call_count == 2
    assert "succeeded" in send.call_args.args[1]


def test_monitor_reports_repeated_poll_errors(monkeypatch):
    get = Mock(side_effect=requests.Timeout())
    send = Mock()
    monkeypatch.setattr(bot.requests, "get", get)
    monkeypatch.setattr(bot, "send_status", send)
    monkeypatch.setattr(bot, "Event", Mock())
    bot.monitor_run(123, "reply-url", "token")
    assert get.call_count == 3
    assert "may still be running" in send.call_args.args[1]


def test_monitor_timeout_is_not_workflow_failure(monkeypatch):
    send = Mock()
    monkeypatch.setattr(bot, "send_status", send)
    monkeypatch.setattr(bot, "monotonic", Mock(side_effect=[0, 1501]))
    bot.monitor_run(123, "reply-url", "token")
    assert "outcome is not yet confirmed" in send.call_args.args[1]
