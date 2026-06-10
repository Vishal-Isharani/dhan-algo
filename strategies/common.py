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


def round_to_tick(price: float, tick_size: float) -> float:
    if tick_size <= 0:
        return round(price, 2)
    return round(round(price / tick_size) * tick_size, 2)


def calc_exit_prices(
    entry: float,
    *,
    target_pct: float | None,
    stop_loss_pct: float | None,
    tick_size: float = 0.05,
) -> tuple[float | None, float | None]:
    """Target/stop as % move on the entry price itself (option premium)."""

    target = round_to_tick(entry * (1 + target_pct / 100), tick_size) if target_pct is not None else None
    stop_loss = round_to_tick(entry * (1 - stop_loss_pct / 100), tick_size) if stop_loss_pct is not None else None
    return target, stop_loss


def calc_option_exit_from_underlying(
    entry: float,
    spot: float,
    delta: float | None,
    option_side: str,
    *,
    target_underlying_pct: float | None,
    stop_underlying_pct: float | None,
    tick_size: float = 0.05,
) -> tuple[float | None, float | None]:
    """Map underlying spot move % to option target/SL using chain delta."""

    side = option_side.upper()
    if side not in ("CE", "PE"):
        raise ValueError(f"option_side must be CE or PE, got {option_side!r}")

    if delta is None:
        delta = 0.5 if side == "CE" else -0.5
    delta = float(delta)

    target_price: float | None = None
    stop_loss: float | None = None

    if target_underlying_pct is not None:
        spot_move = spot * (target_underlying_pct / 100)
        if side == "CE":
            target_price = entry + delta * spot_move
        else:
            target_price = entry + delta * (-spot_move)

    if stop_underlying_pct is not None:
        spot_move = spot * (stop_underlying_pct / 100)
        if side == "CE":
            stop_loss = entry + delta * (-spot_move)
        else:
            stop_loss = entry + delta * spot_move

    if target_price is not None:
        target_price = round_to_tick(target_price, tick_size)
        if target_price <= entry:
            target_price = round_to_tick(entry + tick_size, tick_size)

    if stop_loss is not None:
        stop_loss = round_to_tick(stop_loss, tick_size)
        if stop_loss >= entry:
            stop_loss = round_to_tick(entry - tick_size, tick_size)
        if stop_loss <= 0:
            stop_loss = tick_size

    return target_price, stop_loss


def order_api_price(order_type: str, estimated_price: float) -> float:
    """Dhan MARKET orders require price=0."""

    return 0.0 if order_type.upper() == "MARKET" else estimated_price
