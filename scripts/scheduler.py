"""Schedule strategy instances on confirmed NSE trading days."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.strategy_loader import load_strategy_runs
from scripts.trading_calendar import is_trading_day
from strategies.base import StrategyRun
from strategies.common import parse_run_time

IST = ZoneInfo("Asia/Kolkata")
STATE_FILE = Path("data/scheduler_state.json")
POLL_SEC = 30
RUN_WINDOW_MIN = 2
PRE_MARKET_CHECK = (9, 10)
BTST_EXIT_CHECK = (9, 13)
MARKET_END = (16, 0)
BTST_EXIT_JOB = "btst-exit"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_run_at(run: StrategyRun) -> str | None:
    return getattr(run.config, "run_at", None)


def _minutes_since_midnight(hour: int, minute: int) -> int:
    return hour * 60 + minute


def _is_past_pre_market_check(now: datetime) -> bool:
    check_mins = _minutes_since_midnight(*PRE_MARKET_CHECK)
    now_mins = _minutes_since_midnight(now.hour, now.minute)
    return now_mins >= check_mins


def _day_state_for(now: datetime) -> dict:
    state = _load_state()
    today = now.date().isoformat()
    day_state = state.get("day", {})
    if day_state.get("date") != today:
        return {"date": today, "checked": False, "is_trading_day": None}
    return day_state


def _update_day_state(now: datetime, *, checked: bool, is_trading: bool | None) -> None:
    state = _load_state()
    state["day"] = {
        "date": now.date().isoformat(),
        "checked": checked,
        "is_trading_day": is_trading,
    }
    _save_state(state)


def confirm_trading_day(now: datetime | None = None) -> bool | None:
    """Check once per day before 9:15 whether today is a trading day."""

    now = now or datetime.now(IST)
    day_state = _day_state_for(now)

    if day_state.get("checked"):
        return day_state.get("is_trading_day")

    if not _is_past_pre_market_check(now):
        return None

    trading = is_trading_day(now.date())
    _update_day_state(now, checked=True, is_trading=trading)

    if trading:
        print(f"Trading day confirmed for {now.date().isoformat()}. Strategies armed.")
    else:
        reason = "weekend" if now.weekday() >= 5 else "NSE holiday"
        print(f"No trading today ({now.date().isoformat()}) — {reason}. Skipping all strategies.")

    return trading


def is_due(run_at: str, now: datetime, last_run_date: str | None) -> bool:
    today = now.date().isoformat()
    if last_run_date == today:
        return False

    hour, minute = parse_run_time(run_at)
    now_mins = _minutes_since_midnight(now.hour, now.minute)
    run_mins = _minutes_since_midnight(hour, minute)
    return run_mins <= now_mins < run_mins + RUN_WINDOW_MIN


def due_runs(runs: list[StrategyRun], now: datetime) -> list[StrategyRun]:
    state = _load_state()
    launched = state.get("launched", {})
    due: list[StrategyRun] = []

    for run in runs:
        run_at = get_run_at(run)
        if not run_at:
            continue
        if is_due(run_at, now, launched.get(run.name)):
            due.append(run)

    return due


def mark_launched(run_name: str, now: datetime) -> None:
    state = _load_state()
    launched = state.get("launched", {})
    launched[run_name] = now.date().isoformat()
    state["launched"] = launched
    _save_state(state)


def launch_strategy(run_name: str) -> int:
    cmd = ["run-strategies", run_name]
    print(f"Launching: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode


def launch_btst_exit() -> int:
    cmd = ["run-btst-exit"]
    print(f"Launching: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode


def btst_exit_due(now: datetime) -> bool:
    state = _load_state()
    launched = state.get("launched", {})
    if launched.get(BTST_EXIT_JOB) == now.date().isoformat():
        return False
    return is_due(f"{BTST_EXIT_CHECK[0]:02d}:{BTST_EXIT_CHECK[1]:02d}", now, launched.get(BTST_EXIT_JOB))


def _seconds_until(dt: datetime) -> int:
    now = datetime.now(IST)
    return max(int((dt - now).total_seconds()), POLL_SEC)


def seconds_until_next_check(now: datetime | None = None) -> int:
    now = now or datetime.now(IST)

    if not _is_past_pre_market_check(now):
        target = now.replace(
            hour=PRE_MARKET_CHECK[0],
            minute=PRE_MARKET_CHECK[1],
            second=0,
            microsecond=0,
        )
        return _seconds_until(target)

    day_state = _day_state_for(now)
    if not day_state.get("checked"):
        return POLL_SEC

    if not day_state.get("is_trading_day"):
        tomorrow = now.date() + timedelta(days=1)
        while True:
            next_start = datetime(
                tomorrow.year,
                tomorrow.month,
                tomorrow.day,
                PRE_MARKET_CHECK[0],
                PRE_MARKET_CHECK[1],
                tzinfo=IST,
            )
            if tomorrow.weekday() < 5:
                break
            tomorrow += timedelta(days=1)
        return _seconds_until(next_start)

    if (now.hour, now.minute) >= MARKET_END:
        tomorrow = now.date() + timedelta(days=1)
        next_start = datetime(
            tomorrow.year,
            tomorrow.month,
            tomorrow.day,
            PRE_MARKET_CHECK[0],
            PRE_MARKET_CHECK[1],
            tzinfo=IST,
        )
        return _seconds_until(next_start)

    return POLL_SEC


def run_scheduler_loop() -> None:
    print("Scheduler started (IST). For VPS production use.")
    print(f"Pre-market trading day check at {PRE_MARKET_CHECK[0]:02d}:{PRE_MARKET_CHECK[1]:02d}")
    print("On trading days, each strategy runs at its own run_at time.")
    print(f"State file: {STATE_FILE}")

    while True:
        now = datetime.now(IST)
        try:
            trading = confirm_trading_day(now)
            if trading:
                runs = load_strategy_runs()
                for run in due_runs(runs, now):
                    exit_code = launch_strategy(run.name)
                    if exit_code == 0:
                        mark_launched(run.name, now)
                    else:
                        print(
                            f"{run.name} exited with code {exit_code} — "
                            "not marked done, may retry within run window",
                            file=sys.stderr,
                        )
                if btst_exit_due(now):
                    exit_code = launch_btst_exit()
                    if exit_code == 0:
                        mark_launched(BTST_EXIT_JOB, now)
        except Exception as exc:
            print(f"Scheduler error: {exc}", file=sys.stderr)

        sleep_for = seconds_until_next_check(now)
        print(f"Next check in {sleep_for}s ({now.strftime('%Y-%m-%d %H:%M')} IST)")
        time.sleep(sleep_for)


def preview_schedule() -> None:
    runs = load_strategy_runs()
    today = datetime.now(IST).date()
    print(f"Today ({today.isoformat()}): trading day = {is_trading_day(today)}")
    print(f"Pre-market check time: {PRE_MARKET_CHECK[0]:02d}:{PRE_MARKET_CHECK[1]:02d} IST")
    print("Scheduled strategy instances:")
    for run in runs:
        run_at = get_run_at(run) or "manual only"
        print(f"  {run.name} ({run.strategy_type}) -> {run_at} IST")
