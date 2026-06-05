"""Run next-morning BTST Nifty exits for open positions."""

from __future__ import annotations

import sys

from scripts.btst_exit import execute_all_btst_exits
from scripts.dhan_helpers import get_client
from scripts.ip_manager import ensure_ip_whitelisted
from scripts.telegram_alert import alert_failure


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    skip_wait = "--now" in args

    try:
        dhan, _ = get_client()
    except ValueError as exc:
        msg = f"Dhan credentials error: {exc}"
        print(f"Error: {exc}", file=sys.stderr)
        alert_failure(msg)
        return 1

    if not ensure_ip_whitelisted():
        msg = "IP not whitelisted for Dhan order APIs"
        print(f"Aborting: {msg}", file=sys.stderr)
        alert_failure(msg)
        return 1

    results = execute_all_btst_exits(dhan, skip_wait=skip_wait)
    print(f"BTST exits completed: {len(results)}")
    return 0


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
