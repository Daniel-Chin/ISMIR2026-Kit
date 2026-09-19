from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


@lru_cache(maxsize=32)
def load_site_config(site_data_path: str) -> dict:
    config_path = Path(site_data_path) / "config.yml"
    if not config_path.exists():
        return {}

    with config_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@lru_cache(maxsize=32)
def load_conference_timezone_name(
    site_data_path: str,
) -> str:
    config = load_site_config(site_data_path)
    return str(config["timezone"])


def load_conference_timezone(
    site_data_path: str,
) -> ZoneInfo:
    timezone_name = load_conference_timezone_name(site_data_path)
    return ZoneInfo(timezone_name)


def _timezone_label(dt: datetime, timezone_name: str) -> str:
    offset = dt.strftime("%z")
    if len(offset) == 5:
        return f"GMT{offset[:3]}:{offset[3:]} ({timezone_name})"
    return timezone_name


def format_session_window(
    start_date: str | None,
    start_time: str | None,
    end_time: str | None,
    timezone_name: str,
) -> str:
    """Format a session window in the configured conference timezone."""
    if not start_date or not start_time or not end_time:
        return "Session time unavailable"

    tz = ZoneInfo(timezone_name)

    try:
        year, month, day = [int(x) for x in str(start_date).split("-")]
        start_hour, start_minute = [int(x) for x in str(start_time).split(":")[:2]]
        end_hour, end_minute = [int(x) for x in str(end_time).split(":")[:2]]
    except (TypeError, ValueError):
        return "Session time unavailable"

    start_local = datetime(year, month, day, start_hour, start_minute, tzinfo=tz)
    end_local = datetime(year, month, day, end_hour, end_minute, tzinfo=tz)
    tz_label = _timezone_label(start_local, timezone_name)
    return (
        f"{start_local.strftime('%a, %d %b %Y')}, "
        f"{start_local.strftime('%H:%M')}-{end_local.strftime('%H:%M')} "
        f"{tz_label}"
    )
