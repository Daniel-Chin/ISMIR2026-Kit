from __future__ import annotations

import os
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv


def load_zoom_redirect_access_token() -> str:
    load_dotenv()

    env_token = os.environ.get("ZOOM_REDIRECT_ACCESS_TOKEN")
    assert env_token
    token = str(env_token).strip()
    assert token
    return token


def build_zoom_redirect_url(
    base_url: str,
    room_id: str,
    access_token: str | None,
    include_token: bool = True,
) -> str:
    # Freeze-time links are consumed from {prefix}/poster_?.html pages, so
    # use a same-directory relative URL rather than an absolute/prefixed URL.
    _ = base_url
    room = quote(str(room_id), safe="")
    no_token = f"zoom.html?room={room}"
    if include_token:
        assert access_token is not None
        token = quote(str(access_token), safe="")
        return f"{no_token}&token={token}"
    return no_token


def strip_zoom_passcode(join_url: str) -> str:
    parsed = urlsplit(str(join_url).strip())
    if not parsed.query:
        return str(join_url).strip()

    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "pwd"
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query_items, doseq=True),
            parsed.fragment,
        )
    )