"""Production scheduler for VPS.

Event-driven (no 30s polling). Each trading day (IST):
    1. Wake at 09:10 — confirm NSE trading day
    2. Wake at each strategy run_at from config
    3. Wake at 09:13 for BTST exits
    4. Sleep after 15:30 until next trading morning

VPS / Docker:
    run-scheduler
    run-scheduler --list
"""

from __future__ import annotations

import sys

from scripts.scheduler import preview_schedule, run_scheduler_loop


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if "--list" in args:
        preview_schedule()
        return 0

    run_scheduler_loop()
    return 0


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
