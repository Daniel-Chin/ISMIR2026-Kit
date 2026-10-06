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
from threading import Event, Thread
from time import monotonic

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
POLL_INTERVAL_SECONDS = 15
MONITOR_TIMEOUT_SECONDS = 25 * 60
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


def github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2026-03-10",
    }


def send_status(response_url: str, message: str) -> None:
    try:
        response = requests.post(
            response_url,
            json={"response_type": "in_channel", "text": message},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException:
        # Exceptions can contain Slack's secret response URL; don't log them.
        logger.error("Could not send website refresh status to Slack")


def monitor_run(run_id: int, response_url: str, github_token: str) -> None:
    """Follow only the dispatched run, within Slack's 30-minute reply window."""
    api_url = GITHUB_DISPATCH_URL.split("/workflows/", 1)[0] + f"/runs/{run_id}"
    run_url = GITHUB_RUNS_URL.split("/actions/", 1)[0] + f"/actions/runs/{run_id}"
    deadline = monotonic() + MONITOR_TIMEOUT_SECONDS
    failures = 0
    while monotonic() < deadline:
        try:
            response = requests.get(
                api_url, headers=github_headers(github_token), timeout=30,
                allow_redirects=False,
            )
            response.raise_for_status()
            run = response.json()
            if not isinstance(run, dict) or "status" not in run:
                raise ValueError("Missing run status")
            failures = 0
            if run["status"] == "completed":
                conclusion = run.get("conclusion") or "unknown"
                if conclusion == "success":
                    message = "Website refresh succeeded. Please visit miniconf to verify your edits."
                elif conclusion == "cancelled":
                    message = "Website refresh was cancelled (a newer refresh may have replaced it)."
                else:
                    message = f"Website refresh did not succeed ({conclusion})."
                send_status(response_url, f"{message} Details: {run_url}")
                return
        except (requests.RequestException, ValueError):
            failures += 1
            if failures >= 3:
                send_status(response_url, f"Unable to monitor website refresh after three failed checks. The workflow may still be running. Check: {run_url}")
                return
        Event().wait(min(POLL_INTERVAL_SECONDS, max(0, deadline - monotonic())))
    send_status(response_url, f"Website refresh monitoring timed out after 25 minutes; its outcome is not yet confirmed. Check: {run_url}")


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

    run_id = None
    try:
        response = requests.post(
            GITHUB_DISPATCH_URL,
            headers=github_headers(github_token),
            json={"ref": GITHUB_REF},
            timeout=30,
            allow_redirects=False,
        )
        if response.status_code in (200, 204):
            if response.status_code == 200:
                try:
                    data = response.json()
                    candidate = data.get("workflow_run_id") if isinstance(data, dict) else None
                    if type(candidate) is int and candidate > 0:
                        run_id = candidate
                except ValueError:
                    pass
            if run_id is not None:
                run_url = GITHUB_RUNS_URL.split("/actions/", 1)[0] + f"/actions/runs/{run_id}"
                message = f"Impatient? Check {run_url}; otherwise, please wait for me to relay the results..."
            else:
                message = f"Website refresh queued, but GitHub returned no run ID so I cannot monitor it. Follow progress: {GITHUB_RUNS_URL}"
        else:
            logger.error("GitHub dispatch failed (HTTP %s)", response.status_code)
            message = f"GitHub rejected the website refresh (HTTP {response.status_code}). Ask the bot maintainer to check its token and workflow configuration."
    except requests.RequestException:
        logger.error("Could not confirm GitHub workflow dispatch")
        message = f"Could not confirm the website refresh. Check {GITHUB_RUNS_URL} before retrying."

    response_url = request.payload["response_url"]
    send_status(response_url, message)
    if run_id is not None:
        Thread(
            target=monitor_run,
            args=(run_id, response_url, github_token),
            name=f"website-refresh-{run_id}",
            daemon=True,
        ).start()


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
