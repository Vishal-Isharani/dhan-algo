"""NSE trading day checks including exchange holidays."""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")
HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
HOLIDAY_CACHE_FILE = Path(".cache/nse_holidays.json")
HOLIDAY_CACHE_TTL_HOURS = 24
FO_SEGMENT = "FO"


def _parse_holiday_date(value: str) -> date:
    if "-" in value and len(value) == 10:
        return date.fromisoformat(value)
    return datetime.strptime(value, "%d-%b-%Y").date()


def _fetch_holidays() -> set[date]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/resources/exchange-communication-holidays",
        }
    )
    session.get("https://www.nseindia.com", timeout=15)
    response = session.get(HOLIDAY_URL, timeout=15)
    response.raise_for_status()
    payload = response.json()

    holidays: set[date] = set()
    for segment in (FO_SEGMENT, "CM"):
        for entry in payload.get(segment, []):
            trading_date = entry.get("tradingDate")
            weekday = str(entry.get("weekDay", ""))
            if not trading_date:
                continue
            parsed = _parse_holiday_date(trading_date)
            if weekday not in ("Saturday", "Sunday"):
                holidays.add(parsed)
    return holidays


def get_holiday_dates(force_refresh: bool = False) -> set[date]:
    if not force_refresh and HOLIDAY_CACHE_FILE.exists():
        age_hours = (time.time() - HOLIDAY_CACHE_FILE.stat().st_mtime) / 3600
        if age_hours < HOLIDAY_CACHE_TTL_HOURS:
            cached = json.loads(HOLIDAY_CACHE_FILE.read_text(encoding="utf-8"))
            return {_parse_holiday_date(item) for item in cached}

    holidays = _fetch_holidays()
    HOLIDAY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOLIDAY_CACHE_FILE.write_text(
        json.dumps(sorted(d.isoformat() for d in holidays), indent=2),
        encoding="utf-8",
    )
    return holidays


def is_trading_day(day: date | None = None) -> bool:
    """Return True for weekday NSE sessions that are not exchange holidays."""

    day = day or datetime.now(IST).date()
    if day.weekday() >= 5:
        return False
    return day not in get_holiday_dates()
