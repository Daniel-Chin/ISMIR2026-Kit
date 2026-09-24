"""Credential routing checks with no Slack API calls."""
import runpy
import sys

import pytest

from long_running_bots import announcement_bot
from utils import slack


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    monkeypatch.setattr(announcement_bot, "load_dotenv", lambda **kwargs: None)
    for prefix in ("", "MOCKUP_"):
        for name in ("SLACK_BOT_TOKEN", "SLACK_USER_TOKEN", "SLACK_TOKEN_ANNOUNCEMENT_BOT"):
            monkeypatch.setenv(prefix + name, prefix + name + "-test")
    for name in ("client_bot", "client_user", "_channel_maps", "_user_maps"):
        monkeypatch.setattr(slack, name, getattr(slack, name))


@pytest.mark.parametrize("is_mockup", [False, True])
def test_workspace_credentials_and_cache_reset(is_mockup):
    prefix = "MOCKUP_" if is_mockup else ""
    slack._channel_maps = ({"old": "COLD"}, {})
    slack._user_maps = ({"old": "UOLD"}, {})
    slack.configure_clients(is_mockup=is_mockup)
    assert slack.client_bot.token == prefix + "SLACK_BOT_TOKEN-test"
    assert slack.client_user.token == prefix + "SLACK_USER_TOKEN-test"
    assert slack._channel_maps is None
    assert slack._user_maps is None
    client = announcement_bot.create_slack_client(is_mockup=is_mockup)
    assert client.token == prefix + "SLACK_TOKEN_ANNOUNCEMENT_BOT-test"


def test_missing_mockup_tokens_never_use_live_credentials(monkeypatch):
    for name in ("SLACK_BOT_TOKEN", "SLACK_USER_TOKEN", "SLACK_TOKEN_ANNOUNCEMENT_BOT"):
        monkeypatch.delenv("MOCKUP_" + name)
    slack.configure_clients(is_mockup=True)
    assert not slack.client_bot.token
    assert not slack.client_user.token
    with pytest.raises(RuntimeError, match="Missing MOCKUP_SLACK_TOKEN_ANNOUNCEMENT_BOT"):
        announcement_bot.create_slack_client(is_mockup=True)


@pytest.mark.parametrize("is_mockup", [False, True])
def test_prep_routes_event_description_credentials(monkeypatch, is_mockup):
    args = ["miniconf_prep.py", "--action", "set-event-channel-desc"]
    if is_mockup:
        args.append("--mockup")
    monkeypatch.setattr(sys, "argv", args)
    calls = []
    monkeypatch.setattr(slack, "batch_set_channel_description_interactive",
                        lambda path: calls.append((path, slack.client_bot.token)))
    runpy.run_module("miniconf_prep", run_name="__main__")
    prefix = "MOCKUP_" if is_mockup else ""
    assert calls == [("sitedata_mock" if is_mockup else "sitedata", prefix + "SLACK_BOT_TOKEN-test")]
