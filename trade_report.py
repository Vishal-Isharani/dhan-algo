"""View stored trade history, PnL summary, and CSV export."""

from __future__ import annotations

import argparse
import json
import sys

from scripts.dhan_helpers import get_client
from scripts.trade_journal import export_trades_csv, list_trades, summary_stats
from scripts.trade_reconcile import reconcile_open_trades


def _format_trade(row: dict) -> str:
    pnl = row.get("pnl")
    pnl_text = f"Rs. {pnl:,.2f}" if pnl is not None else "-"
    entry = row.get("entry_fill_price") or row.get("entry_price")
    exit_val = row.get("exit_fill_price") or row.get("exit_price")
    return (
        f"#{row['id']} [{row.get('strategy_type')}/{row['strategy_name']}] "
        f"{row.get('trading_symbol') or row.get('symbol')} "
        f"{row.get('status')} entry={entry} exit={exit_val} "
        f"pnl={pnl_text} ({row.get('exit_reason') or '-'})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="View trade journal and PnL summary.")
    parser.add_argument("--strategy", help="Filter by strategy instance name")
    parser.add_argument("--type", dest="strategy_type", help="Filter by strategy type")
    parser.add_argument("--limit", type=int, default=20, help="Number of trades to show")
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    parser.add_argument(
        "--export-csv",
        metavar="PATH",
        help="Export all matching trades to CSV (e.g. data/trades_export.csv)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Reconcile open trades with Dhan before showing the report",
    )
    args = parser.parse_args(argv)

    if args.sync:
        try:
            dhan, _ = get_client()
            results = reconcile_open_trades(
                dhan,
                strategy_name=args.strategy,
                strategy_type=args.strategy_type,
            )
            if results:
                print(f"Synced {len(results)} trade(s) from Dhan.")
            else:
                print("No open trades needed syncing.")
            print()
        except ValueError as exc:
            print(f"Sync skipped: {exc}", file=sys.stderr)
            return 1

    if args.export_csv:
        count = export_trades_csv(
            args.export_csv,
            strategy_name=args.strategy,
            strategy_type=args.strategy_type,
        )
        print(f"Exported {count} trade(s) to {args.export_csv}")
        return 0

    stats = summary_stats(strategy_name=args.strategy, strategy_type=args.strategy_type)
    trades = list_trades(
        strategy_name=args.strategy,
        strategy_type=args.strategy_type,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps({"summary": stats, "trades": trades}, indent=2, default=str))
        return 0

    label = args.strategy or args.strategy_type or "all strategies"
    print(f"Trade summary ({label})")
    def _num(key: str) -> float:
        value = stats.get(key)
        return 0 if value is None else value

    print(f"  Total trades:  {int(_num('total_trades'))}")
    print(f"  Closed trades: {int(_num('closed_trades'))}")
    print(f"  Targets:       {int(_num('targets'))}")
    print(f"  Stop losses:   {int(_num('stop_losses'))}")
    print(f"  EOD exits:     {int(_num('eod_exits'))}")
    print(f"  Failures:      {int(_num('failures'))}")
    print(f"  Total PnL:     Rs. {_num('total_pnl'):,.2f}")
    print(f"  Avg PnL:       Rs. {_num('avg_pnl'):,.2f}")
    print()
    print("Export full history: uv run trade-report --export-csv data/trades_export.csv")
    print()

    if not trades:
        print("No trades recorded yet.")
        return 0

    print("Recent trades:")
    for row in trades:
        print(f"  {_format_trade(row)}")

    return 0


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
