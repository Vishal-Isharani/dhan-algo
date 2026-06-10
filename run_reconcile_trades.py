"""Reconcile open journal trades with live Dhan positions."""

from __future__ import annotations

import argparse
import sys

from scripts.dhan_helpers import get_client
from scripts.trade_reconcile import reconcile_open_trades


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync open trades in the journal with Dhan positions and fills.",
    )
    parser.add_argument("--strategy", help="Filter by strategy instance name")
    parser.add_argument("--type", dest="strategy_type", help="Filter by strategy type")
    parser.add_argument("--dry-run", action="store_true", help="Show updates without writing")
    args = parser.parse_args(argv)

    try:
        dhan, _ = get_client()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    results = reconcile_open_trades(
        dhan,
        strategy_name=args.strategy,
        strategy_type=args.strategy_type,
        dry_run=args.dry_run,
    )

    if not results:
        print("No open trades needed reconciliation.")
        return 0

    label = "Would reconcile" if args.dry_run else "Reconciled"
    print(f"{label} {len(results)} trade(s):")
    for row in results:
        fill = row.get("exit_fill_price") or row.get("exit_price")
        fill_text = f"Rs. {fill:,.2f}" if fill is not None else "unknown"
        print(
            f"  #{row['trade_id']} {row.get('trading_symbol')} "
            f"-> {row['status']} ({row['exit_reason']}) exit={fill_text}"
        )
    return 0


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
