"""
Listen for /push-sheet-to-website and reply "under construction".

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

GitHub workflow dispatch is not implemented; no GitHub token is needed yet.
"""

import logging
import os
import ssl
from threading import Event

import certifi
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.client import BaseSocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

COMMAND = "/push-sheet-to-website"
logger = logging.getLogger(__name__)


def handle_request(client: BaseSocketModeClient, request: SocketModeRequest) -> None:
    """Acknowledge every envelope and respond to the supported slash command."""
    payload = None
    if request.type == "slash_commands" and request.payload.get("command") == COMMAND:
        payload = {"response_type": "in_channel", "text": "under construction"}
    client.send_socket_mode_response(
        SocketModeResponse(envelope_id=request.envelope_id, payload=payload)
    )


def main() -> None:
    load_dotenv()
    bot_token = os.environ.get("SLACK_BOT_TOKEN_SELF_SERVICE", "").strip()
    app_token = os.environ.get("SLACK_APP_TOKEN_SELF_SERVICE", "").strip()
    assert bot_token
    assert app_token

    # Match utils.slack's certificate and rate-limit handling, using this bot's
    # own token instead of the shared SLACK_TOKEN client.
    web_client = WebClient(
        token=bot_token, ssl=ssl.create_default_context(cafile=certifi.where())
    )
    web_client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    client = SocketModeClient(app_token=app_token, web_client=web_client)
    client.socket_mode_request_listeners.append(handle_request)
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
