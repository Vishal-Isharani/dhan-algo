"""Reconcile open journal trades with live Dhan positions and fills."""

from __future__ import annotations

from typing import Any

from scripts.dhan_helpers import unwrap_sdk_data
from scripts.order_monitor import (
    TRADED_STATUSES,
    _entry_fill_price,
    _exit_fill_price,
    _fetch_super_orders,
    _find_super_order,
    _leg_status,
    _trade_book_fills,
    _weighted_trade_price,
)
from scripts.trade_journal import get_open_trades, update_trade_exit
from strategies.base import PreparedOrder


def _fetch_positions_map(dhan_client) -> dict[str, dict] | None:
    try:
        response = dhan_client.get_positions()
        positions = unwrap_sdk_data(response)
    except (ValueError, TypeError, AttributeError):
        return None

    if not isinstance(positions, list):
        return {}

    by_security: dict[str, dict] = {}
    for position in positions:
        security_id = str(position.get("securityId") or "")
        if security_id:
            by_security[security_id] = position
    return by_security


def _fetch_trade_book(dhan_client) -> list[dict]:
    try:
        response = dhan_client.get_trade_book()
        trades = unwrap_sdk_data(response)
    except (ValueError, TypeError, AttributeError):
        return []

    if isinstance(trades, list):
        return trades
    if isinstance(trades, dict):
        return [trades]
    return []


def is_position_closed(dhan_client, security_id: str) -> bool | None:
    """Return True when the broker shows no open net qty for the security."""

    if not security_id:
        return None

    positions = _fetch_positions_map(dhan_client)
    if positions is None:
        return None

    position = positions.get(str(security_id))
    if position is None:
        return True

    return int(position.get("netQty") or 0) == 0


def _sell_fill_from_position(positions: dict[str, dict] | None, security_id: str) -> float | None:
    if not positions:
        return None
    position = positions.get(str(security_id))
    if not position:
        return None
    sell_qty = int(position.get("sellQty") or 0)
    sell_avg = position.get("sellAvg")
    if sell_qty <= 0 or sell_avg is None:
        return None
    try:
        price = float(sell_avg)
    except (TypeError, ValueError):
        return None
    return round(price, 2) if price > 0 else None


def _sell_fill_from_trade_book(trades: list[dict], security_id: str) -> float | None:
    matched: list[dict] = []
    for trade in trades:
        if str(trade.get("securityId") or "") != str(security_id):
            continue
        txn = str(trade.get("transactionType") or "").upper()
        if txn == "SELL":
            matched.append(trade)
    return _weighted_trade_price(matched, "SELL")


def _resolve_exit_fill(
    dhan_client,
    trade: dict,
    *,
    order: dict | None,
    positions: dict[str, dict] | None,
) -> tuple[float | None, float | None]:
    security_id = str(trade.get("security_id") or "")
    order_id = str(trade.get("order_id") or "")

    entry_fill = (
        float(trade["entry_fill_price"])
        if trade.get("entry_fill_price") is not None
        else None
    )
    exit_fill: float | None = None

    if order_id:
        book_entry, book_exit = _trade_book_fills(dhan_client, order_id)
        if entry_fill is None and book_entry is not None:
            entry_fill = book_entry
        if book_exit is not None:
            exit_fill = book_exit

    if exit_fill is None:
        exit_fill = _sell_fill_from_trade_book(_fetch_trade_book(dhan_client), security_id)

    if exit_fill is None:
        exit_fill = _sell_fill_from_position(positions, security_id)

    if exit_fill is None and order_id:
        planned = None
        if order and _leg_status(order, "TARGET_LEG") in TRADED_STATUSES:
            planned = trade.get("target_price")
        elif order and _leg_status(order, "STOP_LOSS_LEG") in TRADED_STATUSES:
            planned = trade.get("stop_loss_price")
        exit_fill = _exit_fill_price(
            order,
            dhan_client,
            order_id,
            leg_name=None,
            planned_price=float(planned) if planned is not None else None,
        )

    if entry_fill is None and order_id:
        entry_fill = _entry_fill_price(order, dhan_client, order_id)

    return exit_fill, entry_fill


def _infer_exit_meta(trade: dict, order: dict | None) -> dict[str, str]:
    if order:
        if _leg_status(order, "TARGET_LEG") in TRADED_STATUSES:
            return {"exit_reason": "target", "status": "target"}
        if _leg_status(order, "STOP_LOSS_LEG") in TRADED_STATUSES:
            return {"exit_reason": "stop_loss", "status": "stop_loss"}
    return {"exit_reason": "manual", "status": "closed"}


def resolve_manual_exit(dhan_client, order_id: str, prepared: PreparedOrder) -> dict[str, Any]:
    """Build exit payload when a monitored super order was closed manually."""

    order = _find_super_order(_fetch_super_orders(dhan_client), order_id)
    trade = {
        "security_id": prepared.security_id,
        "order_id": order_id,
        "entry_price": prepared.entry_price,
        "target_price": prepared.target_price,
        "stop_loss_price": prepared.stop_loss_price,
        "quantity": prepared.quantity,
        "lot_size": prepared.lot_size,
        "symbol": prepared.symbol,
        "trading_symbol": prepared.trading_symbol,
    }
    positions = _fetch_positions_map(dhan_client)
    meta = _infer_exit_meta(trade, order)
    exit_fill, entry_fill = _resolve_exit_fill(
        dhan_client,
        trade,
        order=order,
        positions=positions,
    )
    planned_exit = exit_fill
    if meta["status"] == "target" and trade.get("target_price") is not None:
        planned_exit = float(trade["target_price"])
    elif meta["status"] == "stop_loss" and trade.get("stop_loss_price") is not None:
        planned_exit = float(trade["stop_loss_price"])

    return {
        "exit_reason": meta["exit_reason"],
        "status": meta["status"],
        "exit_price": planned_exit,
        "exit_fill_price": exit_fill,
        "entry_fill_price": entry_fill,
        "notes": "Detected closed position at broker during monitoring",
    }


def reconcile_trade(dhan_client, trade: dict, *, dry_run: bool = False) -> dict[str, Any] | None:
    """Close a journal trade when the broker no longer holds the position."""

    security_id = str(trade.get("security_id") or "")
    closed = is_position_closed(dhan_client, security_id)
    if closed is not True:
        return None

    order_id = str(trade.get("order_id") or "")
    order = _find_super_order(_fetch_super_orders(dhan_client), order_id) if order_id else None
    positions = _fetch_positions_map(dhan_client)
    meta = _infer_exit_meta(trade, order)
    exit_fill, entry_fill = _resolve_exit_fill(
        dhan_client,
        trade,
        order=order,
        positions=positions,
    )

    planned_exit = exit_fill
    if meta["status"] == "target" and trade.get("target_price") is not None:
        planned_exit = float(trade["target_price"])
    elif meta["status"] == "stop_loss" and trade.get("stop_loss_price") is not None:
        planned_exit = float(trade["stop_loss_price"])

    result = {
        "trade_id": int(trade["id"]),
        "trading_symbol": trade.get("trading_symbol") or trade.get("symbol"),
        "exit_reason": meta["exit_reason"],
        "status": meta["status"],
        "exit_price": planned_exit,
        "exit_fill_price": exit_fill,
        "entry_fill_price": entry_fill,
    }

    if dry_run:
        result["dry_run"] = True
        return result

    update_trade_exit(
        int(trade["id"]),
        exit_reason=meta["exit_reason"],
        exit_price=planned_exit,
        status=meta["status"],
        notes="Reconciled from Dhan positions/trade book",
        entry_fill_price=entry_fill,
        exit_fill_price=exit_fill,
    )
    return result


def reconcile_open_trades(
    dhan_client,
    *,
    strategy_name: str | None = None,
    strategy_type: str | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Sync all open journal trades against live broker state."""

    trades = get_open_trades(strategy_name=strategy_name, strategy_type=strategy_type)
    if not trades:
        return []

    results: list[dict[str, Any]] = []
    for trade in trades:
        reconciled = reconcile_trade(dhan_client, trade, dry_run=dry_run)
        if reconciled:
            results.append(reconciled)
    return results
