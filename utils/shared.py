from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import cast, overload
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
        return f"(GMT{offset[:3]}:{offset[3:]}, {timezone_name})"
    return f"({timezone_name})"


def _normalize_session_datetime(dt: datetime, zone_info: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=zone_info)
    return dt.astimezone(zone_info)


def _format_session_window_datetimes(
    start_datetime: datetime,
    end_datetime: datetime,
    zone_info: ZoneInfo,
) -> str:
    start_local = _normalize_session_datetime(start_datetime, zone_info)
    end_local = _normalize_session_datetime(end_datetime, zone_info)
    tz_label = _timezone_label(start_local, zone_info.key)

    if start_local.date() != end_local.date():
        return (
            f"{start_local.strftime('%a, %b %d, %H:%M')} - "
            f"{end_local.strftime('%a, %b %d, %H:%M')} "
            f"{tz_label}"
        )

    return (
        f"{start_local.strftime('%a, %b %d')}, "
        f"{start_local.strftime('%H:%M')}-{end_local.strftime('%H:%M')} "
        f"{tz_label}"
    )


@overload
def format_session_window(
    start_date: str | None,
    start_time: str | None,
    end_time: str | None,
    timezone_name: str,
    /,
) -> str:
    ...


@overload
def format_session_window(
    start_datetime: datetime,
    end_datetime: datetime,
    zone_info: ZoneInfo,
    /,
) -> str:
    ...


def format_session_window(
    *args: str | datetime | ZoneInfo | None,
) -> str:
    """Format a session window in the specified timezone.

    Examples:
        >>> format_session_window("2026-01-01", "09:00", "10:30", "UTC")
        'Thu, Jan 01, 09:00-10:30 (GMT+00:00, UTC)'
        >>> format_session_window("2026-01-01", "23:30", "00:15", "UTC")
        'Thu, Jan 01, 23:30 - Fri, Jan 02, 00:15 (GMT+00:00, UTC)'
    """
    if len(args) == 3 and isinstance(args[0], datetime):
        start_datetime, end_datetime, zone_info = args
        if not isinstance(end_datetime, datetime):
            raise TypeError("end_datetime must be a datetime")
        if not isinstance(zone_info, ZoneInfo):
            raise TypeError("zone_info must be a ZoneInfo")

        return _format_session_window_datetimes(
            cast(datetime, start_datetime),
            end_datetime,
            zone_info,
        )

    if len(args) != 4:
        raise TypeError("format_session_window expects either 3 or 4 positional arguments")

    start_date, start_time, end_time, timezone_name = args

    if not start_date or not start_time or not end_time:
        return "Session time unavailable"
    if timezone_name is None or not isinstance(timezone_name, str):
        raise TypeError("timezone_name is required with string inputs")

    tz = ZoneInfo(timezone_name)

    try:
        year, month, day = [int(x) for x in str(start_date).split("-")]
        start_hour, start_minute = [int(x) for x in str(start_time).split(":")[:2]]
        end_hour, end_minute = [int(x) for x in str(end_time).split(":")[:2]]
    except (TypeError, ValueError):
        return "Session time unavailable"

    start_local = datetime(year, month, day, start_hour, start_minute, tzinfo=tz)
    end_local = datetime(year, month, day, end_hour, end_minute, tzinfo=tz)
    if end_local < start_local:
        end_local += timedelta(days=1)

    return _format_session_window_datetimes(start_local, end_local, tz)
