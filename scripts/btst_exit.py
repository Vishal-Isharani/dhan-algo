"""Next-morning exit logic for open BTST Nifty positions."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from dhanhq import dhanhq

from scripts.dhan_helpers import unwrap_sdk_data
from scripts.nse_client import NSEClient
from scripts.telegram_alert import alert_failure, alert_success
from scripts.trade_journal import get_open_trades, update_trade_exit
from strategies.common import wait_until_run_time

IST = ZoneInfo("Asia/Kolkata")
BTST_STRATEGY_TYPE = "btst_nifty"


def _parse_config(raw: str | dict) -> dict:
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


def _preopen_confirms(direction: str, change_pct: float, threshold: float) -> bool:
    if direction == "bullish":
        return change_pct > threshold
    if direction == "bearish":
        return change_pct < -threshold
    return False


def _exit_time_for_trade(trade: dict, preopen_change: float) -> tuple[str, str]:
    config = _parse_config(trade.get("strategy_config", "{}"))
    inner = config.get("config", config)
    direction = trade.get("direction") or "bullish"
    threshold = float(inner.get("preopen_confirm_pct", 0.2))
    early = inner.get("exit_early_at", "09:15")
    late = inner.get("exit_late_at", "09:20")

    if _preopen_confirms(direction, preopen_change, threshold):
        return late, "preopen_confirmed"
    return early, "preopen_against"


def _place_exit_order(
    dhan_client,
    *,
    security_id: str,
    quantity: int,
    product: str,
    trading_symbol: str,
) -> dict:
    return dhan_client.place_order(
        security_id=security_id,
        exchange_segment=dhanhq.NSE_FNO,
        transaction_type=dhanhq.SELL,
        quantity=quantity,
        order_type=dhanhq.MARKET,
        product_type=product,
        price=0.0,
        validity=dhanhq.DAY,
        tag="btst_nifty_exit",
    )


def _exit_fill_from_response(dhan_client, order_id: str | None) -> float | None:
    if not order_id:
        return None
    try:
        response = dhan_client.get_order_by_id(order_id)
        data = unwrap_sdk_data(response)
        for key in ("avgTradedPrice", "tradedPrice", "price"):
            value = data.get(key)
            if value is not None and float(value) > 0:
                return round(float(value), 2)
    except (ValueError, TypeError, AttributeError):
        return None
    return None


def execute_btst_exit(
    dhan_client,
    trade: dict,
    *,
    skip_wait: bool = False,
    preopen_change: float | None = None,
) -> dict[str, Any]:
    """Exit one open BTST trade using pre-open rules."""

    config = _parse_config(trade.get("strategy_config", "{}"))
    inner = config.get("config", config)
    check_at = inner.get("exit_check_at", "09:13")
    trading_symbol = trade.get("trading_symbol") or trade.get("symbol")
    security_id = trade.get("security_id")
    quantity = int(trade.get("quantity") or 0)
    product = inner.get("product", "MARGIN")

    if not security_id or quantity <= 0:
        raise ValueError(f"Trade {trade.get('id')} missing security_id or quantity")

    if preopen_change is None:
        if not skip_wait:
            wait_until_run_time(check_at)
        preopen_change = NSEClient().get_nifty_preopen_change_pct()

    exit_at, reason = _exit_time_for_trade(trade, preopen_change)
    if not skip_wait:
        wait_until_run_time(exit_at)

    response = _place_exit_order(
        dhan_client,
        security_id=str(security_id),
        quantity=quantity,
        product=product,
        trading_symbol=str(trading_symbol),
    )
    if response.get("status") != "success":
        raise ValueError(response.get("remarks") or "BTST exit order rejected")

    data = unwrap_sdk_data(response)
    order_id = data.get("orderId")
    exit_fill = _exit_fill_from_response(dhan_client, str(order_id) if order_id else None)

    status = "closed"
    notes = (
        f"preopen {preopen_change:+.2f}%; exit {exit_at}; "
        f"reason={reason}; order={order_id}"
    )
    update_trade_exit(
        int(trade["id"]),
        exit_reason=reason,
        exit_price=exit_fill,
        status=status,
        notes=notes,
        exit_fill_price=exit_fill,
    )

    alert_success(
        f"[BTST exit] {trading_symbol}\n"
        f"Pre-open: {preopen_change:+.2f}%\n"
        f"Exit @ {exit_at} ({reason})\n"
        f"Order ID: {order_id}"
    )
    return {
        "trade_id": trade["id"],
        "preopen_change_pct": preopen_change,
        "exit_at": exit_at,
        "exit_reason": reason,
        "order_id": order_id,
        "exit_fill_price": exit_fill,
    }


def execute_all_btst_exits(dhan_client, *, skip_wait: bool = False) -> list[dict[str, Any]]:
    """Exit every open BTST Nifty position."""

    trades = get_open_trades(strategy_type=BTST_STRATEGY_TYPE)
    if not trades:
        print("No open BTST Nifty trades to exit.")
        return []

    preopen_change: float | None = None
    results: list[dict[str, Any]] = []
    for index, trade in enumerate(trades):
        try:
            result = execute_btst_exit(
                dhan_client,
                trade,
                skip_wait=skip_wait,
                preopen_change=preopen_change,
            )
            if index == 0:
                preopen_change = result["preopen_change_pct"]
                print(f"Nifty pre-open change: {preopen_change:+.2f}%")
            results.append(result)
        except Exception as exc:
            msg = f"[BTST exit] trade {trade.get('id')} failed: {exc}"
            print(msg)
            alert_failure(msg)
        time.sleep(1)
    return results
