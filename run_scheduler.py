"""Production scheduler for VPS.

Flow each trading day:
    1. At 09:10 IST — check NSE trading day (weekday + not holiday)
    2. If trading day — arm all enabled strategies
    3. Each strategy runs at its own run_at from config (e.g. 09:15)

VPS:
    uv run run-scheduler
    uv run run-scheduler --list

Mac (testing):
    uv run run-strategies --now top-mover-gainers
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
