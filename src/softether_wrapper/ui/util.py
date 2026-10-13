"""Small presentation helpers shared by the UI pages."""

from __future__ import annotations

from datetime import datetime


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{value} B"


def human_duration(started: str | None, now: datetime | None = None) -> str:
    if not started:
        return "-"
    parsed = _parse_vpn_time(started)
    if parsed is None:
        return started
    now = now or datetime.now()
    seconds = int((now - parsed).total_seconds())
    if seconds < 0:
        return "-"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _parse_vpn_time(value: str) -> datetime | None:
    # Example: "2026-10-09 (Fri) 17:49:40"
    import re

    match = re.search(r"(\d{4}-\d{2}-\d{2}).*?(\d{1,2}:\d{2}:\d{2})", value)
    if not match:
        match = re.search(r"(\d{4}-\d{2}-\d{2}).*?(\d{1,2}:\d{2})", value)
        if not match:
            return None
        return datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M")
    return datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M:%S")
