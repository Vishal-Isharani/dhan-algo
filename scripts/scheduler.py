"""Schedule strategy instances on confirmed NSE trading days."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.strategy_loader import load_strategy_runs
from scripts.trading_calendar import is_trading_day
from strategies.base import StrategyRun
from strategies.common import parse_run_time

IST = ZoneInfo("Asia/Kolkata")
STATE_FILE = Path("data/scheduler_state.json")
PRE_MARKET_CHECK = (9, 10)
BTST_EXIT_CHECK = (9, 13)
MARKET_END = (15, 30)
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


def _at_time(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, 0, tzinfo=IST)


def _run_at_on(day: date, run_at: str) -> datetime:
    hour, minute = parse_run_time(run_at)
    return _at_time(day, hour, minute)


def _market_end_on(day: date) -> datetime:
    return _at_time(day, *MARKET_END)


def _pre_market_on(day: date) -> datetime:
    return _at_time(day, *PRE_MARKET_CHECK)


def _next_morning(day: date) -> datetime:
    candidate = day + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return _pre_market_on(candidate)


def _launched_on(name: str, day: date) -> bool:
    launched = _load_state().get("launched", {})
    return launched.get(name) == day.isoformat()


def mark_attempted(run_name: str, now: datetime) -> None:
    """Record that a scheduled job ran today — success or failure, no retries."""

    state = _load_state()
    launched = state.get("launched", {})
    launched[run_name] = now.date().isoformat()
    state["launched"] = launched
    _save_state(state)


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
    """Check once per day at/after 09:10 whether today is a trading day."""

    now = now or datetime.now(IST)
    day_state = _day_state_for(now)

    if day_state.get("checked"):
        return day_state.get("is_trading_day")

    if now < _pre_market_on(now.date()):
        return None

    trading = is_trading_day(now.date())
    _update_day_state(now, checked=True, is_trading=trading)

    if trading:
        print(f"Trading day confirmed for {now.date().isoformat()}. Strategies armed.")
    else:
        reason = "weekend" if now.weekday() >= 5 else "NSE holiday"
        print(f"No trading today ({now.date().isoformat()}) — {reason}. Skipping all strategies.")

    return trading


def _pending_jobs(runs: list[StrategyRun], day: date) -> list[tuple[datetime, str, str]]:
    """Return sorted (scheduled_time, job_type, name) not yet run today."""

    jobs: list[tuple[datetime, str, str]] = []
    market_end = _market_end_on(day)

    btst_time = _at_time(day, *BTST_EXIT_CHECK)
    if btst_time <= market_end and not _launched_on(BTST_EXIT_JOB, day):
        jobs.append((btst_time, "btst_exit", BTST_EXIT_JOB))

    for run in runs:
        run_at = get_run_at(run)
        if not run_at:
            continue
        scheduled = _run_at_on(day, run_at)
        if scheduled > market_end:
            continue
        if not _launched_on(run.name, day):
            jobs.append((scheduled, "strategy", run.name))

    jobs.sort(key=lambda item: item[0])
    return jobs


def _next_wake(now: datetime, runs: list[StrategyRun]) -> datetime:
    """Return the exact next datetime the scheduler should wake up."""

    today = now.date()
    market_end = _market_end_on(today)

    if now >= market_end:
        wake = _next_morning(today)
        print(f"Market closed ({MARKET_END[0]:02d}:{MARKET_END[1]:02d} IST). Sleeping until {wake:%Y-%m-%d %H:%M} IST.")
        return wake

    pre_market = _pre_market_on(today)
    if now < pre_market:
        return pre_market

    trading = confirm_trading_day(now)
    if trading is None:
        return pre_market

    if not trading:
        return _next_morning(today)

    pending = _pending_jobs(runs, today)
    if not pending:
        return market_end

    scheduled, _, _ = pending[0]
    if scheduled <= now:
        return now

    return scheduled


def launch_strategy(run_name: str) -> int:
    cmd = ["run-strategies", run_name]
    print(f"Launching: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode


def launch_btst_exit() -> int:
    cmd = ["run-btst-exit"]
    print(f"Launching: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode


def _sleep_until(target: datetime) -> None:
    seconds = int((target - datetime.now(IST)).total_seconds())
    if seconds > 0:
        print(f"Sleeping until {target:%Y-%m-%d %H:%M} IST ({seconds}s)")
        time.sleep(seconds)


def _run_due_jobs(now: datetime, runs: list[StrategyRun]) -> None:
    """Run jobs scheduled for now. Each job runs at most once per day."""

    for scheduled, job_type, name in _pending_jobs(runs, now.date()):
        if scheduled > now:
            break

        if job_type == "btst_exit":
            print(f"Running BTST exit at {now:%H:%M} IST")
            exit_code = launch_btst_exit()
            if exit_code != 0:
                print(f"BTST exit failed (exit {exit_code}) — not retrying today", file=sys.stderr)
            mark_attempted(name, now)
            continue

        print(f"Running {name} at {now:%H:%M} IST (scheduled {scheduled:%H:%M})")
        exit_code = launch_strategy(name)
        if exit_code != 0:
            print(f"{name} failed (exit {exit_code}) — not retrying today", file=sys.stderr)
        mark_attempted(name, now)


def run_scheduler_loop() -> None:
    print("Scheduler started (IST). Event-driven — no polling during market hours.")
    print(f"Pre-market check: {PRE_MARKET_CHECK[0]:02d}:{PRE_MARKET_CHECK[1]:02d} IST")
    print(f"Market close sleep: {MARKET_END[0]:02d}:{MARKET_END[1]:02d} IST")
    print(f"State file: {STATE_FILE}")

    while True:
        now = datetime.now(IST)
        try:
            runs = load_strategy_runs()
            next_wake = _next_wake(now, runs)

            if next_wake > now:
                _sleep_until(next_wake)
                continue

            _run_due_jobs(datetime.now(IST), runs)
        except Exception as exc:
            print(f"Scheduler error: {exc}", file=sys.stderr)
            time.sleep(60)


def preview_schedule() -> None:
    runs = load_strategy_runs()
    today = datetime.now(IST).date()
    print(f"Today ({today.isoformat()}): trading day = {is_trading_day(today)}")
    print(f"Pre-market check: {PRE_MARKET_CHECK[0]:02d}:{PRE_MARKET_CHECK[1]:02d} IST")
    print(f"Market close sleep: {MARKET_END[0]:02d}:{MARKET_END[1]:02d} IST")
    print("Scheduled strategy instances:")
    for run in runs:
        run_at = get_run_at(run) or "manual only"
        print(f"  {run.name} ({run.strategy_type}) -> {run_at} IST")
    print(f"BTST exit job -> {BTST_EXIT_CHECK[0]:02d}:{BTST_EXIT_CHECK[1]:02d} IST")
    wake = _next_wake(datetime.now(IST), runs)
    print(f"Next wake: {wake:%Y-%m-%d %H:%M} IST")
