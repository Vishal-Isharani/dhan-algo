"""Monitor super orders for target and stop-loss exits."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.dhan_helpers import unwrap_sdk_data
from scripts.telegram_alert import alert_failure, alert_stop_loss, alert_target
from strategies.base import PreparedOrder

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = (15, 30)
EXIT_LEGS = {"TARGET_LEG", "STOP_LOSS_LEG"}
TRADED_STATUSES = {"TRADED", "CLOSED"}


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


def _leg_status(order: dict, leg_name: str) -> str | None:
    for leg in order.get("legDetails") or []:
        if leg.get("legName") == leg_name:
            return str(leg.get("orderStatus") or "")
    return None


def monitor_super_order(
    dhan_client,
    order_id: str,
    prepared: PreparedOrder,
    *,
    poll_sec: int = 30,
) -> dict | None:
    """Poll super order status until target, stop loss, or market close."""

    symbol = prepared.trading_symbol
    print(f"Monitoring {symbol} (order {order_id}) for target/SL...")

    while _market_still_open():
        response = dhan_client.get_super_order_list()
        orders = unwrap_sdk_data(response)
        if not isinstance(orders, list):
            orders = []

        order = _find_super_order(orders, order_id)
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
                return {
                    "exit_reason": "failed",
                    "exit_price": None,
                    "status": "failed",
                }

            target_status = _leg_status(order, "TARGET_LEG")
            sl_status = _leg_status(order, "STOP_LOSS_LEG")

            if target_status in TRADED_STATUSES:
                msg = (
                    f"{symbol}\n"
                    f"Target: Rs. {prepared.target_price:,.2f}\n"
                    f"Entry: Rs. {prepared.entry_price:,.2f}"
                )
                alert_target(msg)
                print("Target hit.")
                return {
                    "exit_reason": "target",
                    "exit_price": prepared.target_price,
                    "status": "target",
                }

            if sl_status in TRADED_STATUSES:
                msg = (
                    f"{symbol}\n"
                    f"Stop Loss: Rs. {prepared.stop_loss_price:,.2f}\n"
                    f"Entry: Rs. {prepared.entry_price:,.2f}"
                )
                alert_stop_loss(msg)
                print("Stop loss hit.")
                return {
                    "exit_reason": "stop_loss",
                    "exit_price": prepared.stop_loss_price,
                    "status": "stop_loss",
                }

        time.sleep(poll_sec)

    print("Market closed — stopped monitoring.")
    return None
