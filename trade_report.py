"""View stored trade history and PnL summary."""

from __future__ import annotations

import argparse
import json
import sys

from scripts.trade_journal import list_trades, summary_stats


def _format_trade(row: dict) -> str:
    pnl = row.get("pnl")
    pnl_text = f"Rs. {pnl:,.2f}" if pnl is not None else "-"
    return (
        f"#{row['id']} [{row.get('strategy_type')}/{row['strategy_name']}] "
        f"{row.get('trading_symbol') or row.get('symbol')} "
        f"{row.get('status')} entry={row.get('entry_price')} exit={row.get('exit_price')} "
        f"pnl={pnl_text} ({row.get('exit_reason') or '-'})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="View trade journal and PnL summary.")
    parser.add_argument("--strategy", help="Filter by strategy instance name")
    parser.add_argument("--type", dest="strategy_type", help="Filter by strategy type")
    parser.add_argument("--limit", type=int, default=20, help="Number of trades to show")
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    args = parser.parse_args(argv)

    stats = summary_stats(strategy_name=args.strategy, strategy_type=args.strategy_type)
    trades = list_trades(
        strategy_name=args.strategy,
        strategy_type=args.strategy_type,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps({"summary": stats, "trades": trades}, indent=2, default=str))
        return 0

    label = args.strategy or "all strategies"
    print(f"Trade summary ({label})")
    def _num(key: str) -> float:
        value = stats.get(key)
        return 0 if value is None else value

    print(f"  Total trades:  {int(_num('total_trades'))}")
    print(f"  Closed trades: {int(_num('closed_trades'))}")
    print(f"  Targets:       {int(_num('targets'))}")
    print(f"  Stop losses:   {int(_num('stop_losses'))}")
    print(f"  Failures:      {int(_num('failures'))}")
    print(f"  Total PnL:     Rs. {_num('total_pnl'):,.2f}")
    print(f"  Avg PnL:       Rs. {_num('avg_pnl'):,.2f}")
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
