"""
Listen for /push-sheet-to-website and dispatch the website refresh workflow.

One-time Slack app setup:  
- Enable Socket Mode and generate an app-level token with connections:write.
- Add the commands bot scope, create /push-sheet-to-website, and install the
    app to the workspace. Socket Mode does not require a public request URL.
- Create a miniconf-self-service channel for chairs to use the command.
- Set these variables in the repository's .env:
    SLACK_BOT_TOKEN_SELF_SERVICE=xoxb-...
    SLACK_APP_TOKEN_SELF_SERVICE=xapp-...

Run from the repository root:  
uv run python -m long_running_bots.self_service_pusher

Set pat=YOUR_TOKEN in ~/secrets/ismir2026-self-service-bot.env.
The token needs access to daniel-chin/ismir2026-kit with Actions: write.
"""

import logging
import os
import ssl
from functools import partial
from pathlib import Path
from threading import Event

import certifi
import requests
from dotenv import dotenv_values, load_dotenv
from slack_sdk import WebClient
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.client import BaseSocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

# These constants should be changed per conference.
GITHUB_TOKEN_FILE = Path("~/secrets/ismir2026-self-service-bot.env").expanduser()
GITHUB_DISPATCH_URL = "https://api.github.com/repos/daniel-chin/ismir2026-kit/actions/workflows/refresh-website.yml/dispatches"
GITHUB_REF = "main"
GITHUB_RUNS_URL = "https://github.com/daniel-chin/ismir2026-kit/actions/workflows/refresh-website.yml"
COMMAND = "/push-sheet-to-website"
logger = logging.getLogger(__name__)


def load_github_token() -> str:
    try:
        token = (dotenv_values(GITHUB_TOKEN_FILE, interpolate=False).get("pat") or "").strip()
    except OSError:
        token = ""
    if not token:
        config_line = next(
            i for i, line in enumerate(Path(__file__).read_text().splitlines(), 1)
            if line.startswith("GITHUB_TOKEN_FILE =")
        )
        raise SystemExit(
            f"GitHub token missing or unreadable. Create {GITHUB_TOKEN_FILE} with pat=YOUR_TOKEN. "
            "Give the token access to daniel-chin/ismir2026-kit with Actions: write. "
            f"To change the path, see {__file__}:{config_line} (GITHUB_TOKEN_FILE)."
        )
    return token


def handle_request(
    client: BaseSocketModeClient, request: SocketModeRequest, *, github_token: str
) -> None:
    """Acknowledge every envelope and respond to the supported slash command."""
    payload = None
    if request.type == "slash_commands" and request.payload.get("command") == COMMAND:
        payload = {"response_type": "in_channel", "text": "Requesting website refresh, please wait..."}
    client.send_socket_mode_response(
        SocketModeResponse(envelope_id=request.envelope_id, payload=payload)
    )
    if payload is None:
        return

    try:
        response = requests.post(
            GITHUB_DISPATCH_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {github_token}",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            json={"ref": GITHUB_REF},
            timeout=30,
            allow_redirects=False,
        )
        if response.status_code in (200, 204):
            message = f"Website refresh queued. Follow progress: {GITHUB_RUNS_URL}"
        else:
            logger.error("GitHub dispatch failed (HTTP %s)", response.status_code)
            message = f"GitHub rejected the website refresh (HTTP {response.status_code}). Ask the bot maintainer to check its token and workflow configuration."
    except requests.RequestException:
        logger.error("Could not confirm GitHub workflow dispatch")
        message = f"Could not confirm the website refresh. Check {GITHUB_RUNS_URL} before retrying."

    try:
        response = requests.post(
            request.payload["response_url"],
            json={"response_type": "in_channel", "text": message},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.error("Could not send website refresh status to Slack")


def main() -> None:
    github_token = load_github_token()
    load_dotenv()
    bot_token = os.environ.get("SLACK_BOT_TOKEN_SELF_SERVICE", "").strip()
    app_token = os.environ.get("SLACK_APP_TOKEN_SELF_SERVICE", "").strip()
    assert bot_token
    assert app_token

    # Match utils.slack's certificate and rate-limit handling, using this bot's
    # own token instead of the shared SLACK_BOT_TOKEN client.
    web_client = WebClient(
        token=bot_token, ssl=ssl.create_default_context(cafile=certifi.where())
    )
    web_client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    client = SocketModeClient(app_token=app_token, web_client=web_client)
    client.socket_mode_request_listeners.append(partial(handle_request, github_token=github_token))
    try:
        client.connect()
        logger.info("Listening for %s", COMMAND)
        Event().wait()
    except KeyboardInterrupt:
        logger.info("Stopping self-service bot")
    finally:
        client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
