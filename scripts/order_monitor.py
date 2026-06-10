"""Monitor super orders for target, stop-loss, and market-close exits."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from dhanhq import dhanhq

from scripts.dhan_helpers import unwrap_sdk_data
from scripts.telegram_alert import alert_failure, alert_stop_loss, alert_target
from strategies.base import PreparedOrder

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = (15, 30)
TRADED_STATUSES = {"TRADED", "CLOSED", "COMPLETE"}
PRICE_KEYS = ("avgTradedPrice", "tradedPrice", "price", "lastTradedPrice")


def _market_still_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    return (now.hour, now.minute) < MARKET_CLOSE


def _find_super_order(orders: list[dict], order_id: str) -> dict | None:
    for order in orders:
        if str(order.get("orderId")) == str(order_id):
            return order
    return None


def _leg_record(order: dict, leg_name: str) -> dict | None:
    for leg in order.get("legDetails") or []:
        if leg.get("legName") == leg_name:
            return leg
    return None


def _leg_status(order: dict, leg_name: str) -> str | None:
    leg = _leg_record(order, leg_name)
    if not leg:
        return None
    return str(leg.get("orderStatus") or "")


def _price_from_record(record: dict | None) -> float | None:
    if not record:
        return None
    for key in PRICE_KEYS:
        value = record.get(key)
        if value is None:
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            return round(price, 2)
    return None


def _weighted_trade_price(trades: list[dict], side: str) -> float | None:
    total_qty = 0
    total_value = 0.0
    for trade in trades:
        txn = str(trade.get("transactionType") or "").upper()
        if txn != side.upper():
            continue
        qty = int(trade.get("tradedQuantity") or trade.get("quantity") or 0)
        price = trade.get("tradedPrice") or trade.get("price")
        if qty <= 0 or price is None:
            continue
        total_qty += qty
        total_value += float(price) * qty
    if total_qty <= 0:
        return None
    return round(total_value / total_qty, 2)


def _trade_book_fills(dhan_client, order_id: str) -> tuple[float | None, float | None]:
    try:
        response = dhan_client.get_trade_book(order_id=str(order_id))
        trades = unwrap_sdk_data(response)
    except (ValueError, TypeError, AttributeError):
        return None, None

    if not isinstance(trades, list):
        trades = [trades] if isinstance(trades, dict) else []

    entry_fill = _weighted_trade_price(trades, "BUY")
    exit_fill = _weighted_trade_price(trades, "SELL")
    return entry_fill, exit_fill


def _entry_fill_price(order: dict | None, dhan_client, order_id: str) -> float | None:
    entry_fill, _ = _trade_book_fills(dhan_client, order_id)
    if entry_fill is not None:
        return entry_fill
    if order:
        leg_fill = _price_from_record(_leg_record(order, "ENTRY_LEG"))
        if leg_fill is not None:
            return leg_fill
        return _price_from_record(order)
    return None


def _exit_fill_price(
    order: dict | None,
    dhan_client,
    order_id: str,
    *,
    leg_name: str | None,
    planned_price: float | None,
) -> float | None:
    _, exit_fill = _trade_book_fills(dhan_client, order_id)
    if exit_fill is not None:
        return exit_fill
    if order and leg_name:
        leg_fill = _price_from_record(_leg_record(order, leg_name))
        if leg_fill is not None:
            return leg_fill
    return planned_price


def _fetch_option_ltp(dhan_client, security_id: str) -> float | None:
    try:
        response = dhan_client.ticker_data({dhanhq.NSE_FNO: [int(security_id)]})
        if response.get("status") != "success":
            return None
        segment = response.get("data", {}).get(dhanhq.NSE_FNO, {})
        quote = segment.get(str(security_id)) or segment.get(int(security_id))
        if not quote:
            return None
        ltp = quote.get("last_price")
        return round(float(ltp), 2) if ltp else None
    except (TypeError, ValueError, KeyError):
        return None


def _fetch_super_orders(dhan_client) -> list[dict]:
    response = dhan_client.get_super_order_list()
    orders = unwrap_sdk_data(response)
    return orders if isinstance(orders, list) else []


def _exit_result(
    *,
    exit_reason: str,
    status: str,
    prepared: PreparedOrder,
    order: dict | None,
    dhan_client,
    order_id: str,
    leg_name: str | None = None,
    planned_exit: float | None = None,
    notes: str = "",
) -> dict[str, Any]:
    entry_fill = _entry_fill_price(order, dhan_client, order_id)
    exit_fill = _exit_fill_price(
        order,
        dhan_client,
        order_id,
        leg_name=leg_name,
        planned_price=planned_exit,
    )
    return {
        "exit_reason": exit_reason,
        "status": status,
        "exit_price": planned_exit,
        "exit_fill_price": exit_fill,
        "entry_fill_price": entry_fill,
        "notes": notes,
    }


def _finalize_at_market_close(
    dhan_client,
    order_id: str,
    prepared: PreparedOrder,
) -> dict[str, Any]:
    order = _find_super_order(_fetch_super_orders(dhan_client), order_id)
    entry_fill = _entry_fill_price(order, dhan_client, order_id)

    if order:
        entry_status = str(order.get("orderStatus") or "")
        if entry_status in {"REJECTED", "CANCELLED"}:
            return _exit_result(
                exit_reason="failed",
                status="failed",
                prepared=prepared,
                order=order,
                dhan_client=dhan_client,
                order_id=order_id,
                notes=order.get("omsErrorDescription") or "Entry rejected at EOD",
            )

        if entry_status not in TRADED_STATUSES:
            return _exit_result(
                exit_reason="entry_not_filled",
                status="failed",
                prepared=prepared,
                order=order,
                dhan_client=dhan_client,
                order_id=order_id,
                notes="Entry order not filled by market close",
            )

        if _leg_status(order, "TARGET_LEG") in TRADED_STATUSES:
            return _exit_result(
                exit_reason="target",
                status="target",
                prepared=prepared,
                order=order,
                dhan_client=dhan_client,
                order_id=order_id,
                leg_name="TARGET_LEG",
                planned_exit=prepared.target_price,
            )

        if _leg_status(order, "STOP_LOSS_LEG") in TRADED_STATUSES:
            return _exit_result(
                exit_reason="stop_loss",
                status="stop_loss",
                prepared=prepared,
                order=order,
                dhan_client=dhan_client,
                order_id=order_id,
                leg_name="STOP_LOSS_LEG",
                planned_exit=prepared.stop_loss_price,
            )

    eod_ltp = _fetch_option_ltp(dhan_client, prepared.security_id)
    notes = "EOD mark-to-market from option LTP" if eod_ltp else "EOD — exit fill unknown"
    return _exit_result(
        exit_reason="market_close",
        status="closed",
        prepared=prepared,
        order=order,
        dhan_client=dhan_client,
        order_id=order_id,
        planned_exit=eod_ltp,
        notes=notes,
    )


def monitor_super_order(
    dhan_client,
    order_id: str,
    prepared: PreparedOrder,
    *,
    poll_sec: int = 30,
) -> dict[str, Any]:
    """Poll super order status until target, stop loss, or market close."""

    symbol = prepared.trading_symbol
    print(f"Monitoring {symbol} (order {order_id}) for target/SL...")

    while _market_still_open():
        order = _find_super_order(_fetch_super_orders(dhan_client), order_id)
        if order:
            entry_status = str(order.get("orderStatus") or "")
            if entry_status in {"REJECTED", "CANCELLED"}:
                msg = (
                    f"{symbol}\n"
                    f"Entry {entry_status.lower()}\n"
                    f"{order.get('omsErrorDescription', '')}"
                )
                alert_failure(msg)
                print(f"Entry {entry_status.lower()}.")
                return _exit_result(
                    exit_reason="failed",
                    status="failed",
                    prepared=prepared,
                    order=order,
                    dhan_client=dhan_client,
                    order_id=order_id,
                    notes=order.get("omsErrorDescription") or entry_status.lower(),
                )

            if _leg_status(order, "TARGET_LEG") in TRADED_STATUSES:
                msg = (
                    f"{symbol}\n"
                    f"Target: Rs. {prepared.target_price:,.2f}\n"
                    f"Entry: Rs. {prepared.entry_price:,.2f}"
                )
                alert_target(msg)
                print("Target hit.")
                return _exit_result(
                    exit_reason="target",
                    status="target",
                    prepared=prepared,
                    order=order,
                    dhan_client=dhan_client,
                    order_id=order_id,
                    leg_name="TARGET_LEG",
                    planned_exit=prepared.target_price,
                )

            if _leg_status(order, "STOP_LOSS_LEG") in TRADED_STATUSES:
                msg = (
                    f"{symbol}\n"
                    f"Stop Loss: Rs. {prepared.stop_loss_price:,.2f}\n"
                    f"Entry: Rs. {prepared.entry_price:,.2f}"
                )
                alert_stop_loss(msg)
                print("Stop loss hit.")
                return _exit_result(
                    exit_reason="stop_loss",
                    status="stop_loss",
                    prepared=prepared,
                    order=order,
                    dhan_client=dhan_client,
                    order_id=order_id,
                    leg_name="STOP_LOSS_LEG",
                    planned_exit=prepared.stop_loss_price,
                )

            if entry_status in TRADED_STATUSES:
                from scripts.trade_reconcile import is_position_closed, resolve_manual_exit

                closed = is_position_closed(dhan_client, prepared.security_id)
                if closed is True:
                    print("Position closed at broker (manual or external exit).")
                    return resolve_manual_exit(dhan_client, order_id, prepared)

        time.sleep(poll_sec)

    print("Market closed — recording EOD exit.")
    result = _finalize_at_market_close(dhan_client, order_id, prepared)
    if result["exit_reason"] == "market_close":
        ltp = result.get("exit_fill_price")
        ltp_text = f"Rs. {ltp:,.2f}" if ltp else "unknown"
        print(f"EOD exit recorded ({ltp_text}).")
    return result
