"""Shared helpers used across strategy modules."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def parse_run_time(run_at: str) -> tuple[int, int]:
    """Parse HH:MM or HH:MM:SS into hour and minute."""

    parts = run_at.strip().split(":")
    if len(parts) < 2:
        raise ValueError(f"Invalid run_at time '{run_at}'; expected HH:MM or HH:MM:SS")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid run_at time '{run_at}'")
    return hour, minute


def wait_until_run_time(run_at: str | None) -> None:
    if not run_at:
        return

    hour, minute = parse_run_time(run_at)
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
