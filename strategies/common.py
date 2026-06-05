"""Shared helpers used across strategy modules."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def wait_until_run_time(run_at: str | None) -> None:
    if not run_at:
        return

    hour, minute = map(int, run_at.split(":"))
    now = datetime.now(IST)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        return

    seconds = (target - now).total_seconds()
    print(f"Waiting until {run_at} IST ({int(seconds)}s)...")
    time.sleep(seconds)


def calc_exit_prices(
    entry: float,
    *,
    target_pct: float | None,
    stop_loss_pct: float | None,
) -> tuple[float | None, float | None]:
    target = round(entry * (1 + target_pct / 100), 2) if target_pct is not None else None
    stop_loss = round(entry * (1 - stop_loss_pct / 100), 2) if stop_loss_pct is not None else None
    return target, stop_loss
