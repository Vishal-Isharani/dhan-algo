"""Run one or more trading strategies on Dhan.

Local testing (Mac):
    uv run run-strategies --now top-mover-gainers

Production (VPS uses run-scheduler instead — see run_scheduler.py):
    uv run run-strategies top-mover-gainers
"""

from __future__ import annotations

import sys

from scripts.dhan_helpers import get_client, unwrap_sdk_data
from scripts.ip_manager import ensure_ip_whitelisted
from scripts.order_monitor import monitor_super_order
from scripts.strategy_loader import load_strategy_runs
from scripts.telegram_alert import alert_failure, alert_success
from scripts.trade_journal import log_trade_failed, log_trade_open, update_trade_exit
from strategies.base import StrategyRun
from strategies.registry import get_strategy


def _extract_order_data(response: dict) -> dict:
    try:
        data = unwrap_sdk_data(response)
    except ValueError:
        data = response.get("data", {})
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data if isinstance(data, dict) else {}


def execute_strategy_run(dhan, run: StrategyRun, *, skip_wait: bool = False) -> int:
    strategy = get_strategy(run.strategy_type)
    label = f"{run.name} ({run.strategy_type})"
    print(f"\n--- Running {label} ---")

    try:
        prepared = strategy.prepare(dhan, run.config, skip_wait=skip_wait)
    except Exception as exc:
        msg = f"[{label}] Strategy failed: {exc}"
        print(msg, file=sys.stderr)
        alert_failure(msg)
        log_trade_failed(
            strategy_name=run.name,
            strategy_type=run.strategy_type,
            strategy_config=run.to_dict(),
            reason=str(exc),
        )
        return 1

    print(strategy.format_summary(prepared, run.config))

    try:
        response = strategy.place_order(dhan, prepared, run.config)
    except Exception as exc:
        msg = f"[{label}] Order failed: {prepared.trading_symbol} — {exc}"
        print(msg, file=sys.stderr)
        alert_failure(msg)
        log_trade_failed(
            strategy_name=run.name,
            strategy_type=run.strategy_type,
            strategy_config=run.to_dict(),
            reason=str(exc),
            prepared=prepared,
        )
        return 1

    if response.get("status") != "success":
        msg = f"[{label}] Order rejected: {prepared.trading_symbol} — {response.get('remarks')}"
        print(msg, file=sys.stderr)
        alert_failure(msg)
        log_trade_failed(
            strategy_name=run.name,
            strategy_type=run.strategy_type,
            strategy_config=run.to_dict(),
            reason=str(response.get("remarks")),
            prepared=prepared,
        )
        return 1

    data = _extract_order_data(response)
    order_id = data.get("orderId")
    order_status = data.get("orderStatus")
    print(f"Order placed: id={order_id} status={order_status}")

    if order_status in {"REJECTED", "CANCELLED"}:
        msg = f"[{label}] Order {order_status.lower()}: {prepared.trading_symbol}"
        alert_failure(msg)
        log_trade_failed(
            strategy_name=run.name,
            strategy_type=run.strategy_type,
            strategy_config=run.to_dict(),
            reason=order_status.lower(),
            prepared=prepared,
        )
        return 1

    trade_id = log_trade_open(
        strategy_name=run.name,
        strategy_type=run.strategy_type,
        strategy_config=run.to_dict(),
        prepared=prepared,
        order_id=str(order_id) if order_id else None,
        order_status=order_status,
        lots=strategy.lots(run.config),
    )

    success_msg = (
        f"[{label}] Order placed: {prepared.trading_symbol}\n"
        f"Entry: Rs. {prepared.entry_price:,.2f}\n"
        f"Qty: {prepared.quantity}\n"
        f"Order ID: {order_id}"
    )
    if prepared.target_price is not None:
        success_msg += f"\nTarget: Rs. {prepared.target_price:,.2f}"
    if prepared.stop_loss_price is not None:
        success_msg += f"\nStop Loss: Rs. {prepared.stop_loss_price:,.2f}"
    alert_success(success_msg)

    if strategy.uses_super_order(run.config) and order_id:
        exit_info = monitor_super_order(
            dhan,
            str(order_id),
            prepared,
            poll_sec=strategy.monitor_poll_sec(run.config),
        )
        if exit_info:
            update_trade_exit(
                trade_id,
                exit_reason=exit_info["exit_reason"],
                exit_price=exit_info.get("exit_price"),
                status=exit_info["status"],
                notes=exit_info.get("notes", ""),
                entry_fill_price=exit_info.get("entry_fill_price"),
                exit_fill_price=exit_info.get("exit_fill_price"),
            )

    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    skip_wait = False
    if "--now" in args:
        skip_wait = True
        args.remove("--now")
    instance_names = args or None

    try:
        runs = load_strategy_runs(instance_names)
    except (FileNotFoundError, ValueError) as exc:
        msg = f"Config error: {exc}"
        print(f"Error: {exc}", file=sys.stderr)
        alert_failure(msg)
        return 1

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

    failures = 0
    for run in runs:
        if execute_strategy_run(dhan, run, skip_wait=skip_wait) != 0:
            failures += 1

    if failures:
        print(f"\nCompleted with {failures} failed strategy(s).", file=sys.stderr)
        return 1

    print(f"\nCompleted {len(runs)} strategy instance(s).")
    return 0


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
