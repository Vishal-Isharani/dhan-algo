"""Buy ATM stock options based on NSE F&O top gainers or losers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from dhanhq import dhanhq

from scripts.dhan_helpers import (
    check_margin,
    fetch_chain_df,
    find_atm_row,
    get_lot_size,
    parse_expiry_list,
    resolve_symbol,
)
from scripts.nse_client import NSEClient, NSEMover
from scripts.validate_order import validate_order
from strategies.base import BaseStrategy, PreparedOrder
from strategies.common import calc_exit_prices, wait_until_run_time

OptionSide = Literal["CE", "PE"]
MoverDirection = Literal["gainers", "loosers"]
STOCK_UNDERLYING_SEGMENT = "NSE_EQ"
OPTION_CHAIN_RATE_LIMIT_SEC = 3


@dataclass(frozen=True)
class TopMoverConfig:
    name: str
    direction: MoverDirection
    rank: int
    lots: int
    product: str
    order_type: str
    expiry: str | None
    run_at: str | None
    target_pct: float | None
    stop_loss_pct: float | None
    trailing_jump: float
    monitor_poll_sec: int


def direction_to_option_side(direction: MoverDirection) -> OptionSide:
    return "CE" if direction == "gainers" else "PE"


class TopMoverOptionsStrategy(BaseStrategy):
    strategy_type = "top_mover_options"

    def parse_config(self, raw: dict, name: str) -> TopMoverConfig:
        direction = raw.get("direction", "gainers")
        if direction not in ("gainers", "loosers"):
            raise ValueError(f"{name}: direction must be 'gainers' or 'loosers'")

        lots = int(raw.get("lots", 1))
        rank = int(raw.get("rank", 1))
        if lots < 1 or rank < 1:
            raise ValueError(f"{name}: lots and rank must be at least 1")

        target_pct = raw.get("target_pct")
        stop_loss_pct = raw.get("stop_loss_pct")

        return TopMoverConfig(
            name=name,
            direction=direction,
            rank=rank,
            lots=lots,
            product=raw.get("product", "INTRADAY"),
            order_type=raw.get("order_type", "LIMIT"),
            expiry=raw.get("expiry"),
            run_at=raw.get("run_at"),
            target_pct=float(target_pct) if target_pct is not None else None,
            stop_loss_pct=float(stop_loss_pct) if stop_loss_pct is not None else None,
            trailing_jump=float(raw.get("trailing_jump", 0)),
            monitor_poll_sec=int(raw.get("monitor_poll_sec", 30)),
        )

    def prepare(self, dhan_client, config: TopMoverConfig) -> PreparedOrder:
        wait_until_run_time(config.run_at)

        nse = NSEClient()
        mover = nse.get_top_mover(config.direction, rank=config.rank)
        option_side = direction_to_option_side(config.direction)
        return self._prepare_order(dhan_client, mover, config, option_side=option_side)

    def _prepare_order(
        self,
        dhan_client,
        mover: NSEMover,
        config: TopMoverConfig,
        *,
        option_side: OptionSide,
    ) -> PreparedOrder:
        resolved = resolve_symbol(mover.symbol, exchange_segment=STOCK_UNDERLYING_SEGMENT)
        if resolved is None:
            raise ValueError(f"Could not resolve Dhan security ID for '{mover.symbol}'")

        underlying_security_id = resolved["security_id"]
        expiry = config.expiry

        if expiry is None:
            expiry_response = dhan_client.expiry_list(
                under_security_id=int(underlying_security_id),
                under_exchange_segment=STOCK_UNDERLYING_SEGMENT,
            )
            expiries = parse_expiry_list(expiry_response)
            if not expiries:
                raise ValueError(f"No option expiries found for {mover.symbol}")
            expiry = expiries[0]

        time.sleep(OPTION_CHAIN_RATE_LIMIT_SEC)
        chain_df, spot = fetch_chain_df(
            dhan_client,
            under_security_id=int(underlying_security_id),
            expiry=expiry,
            under_exchange_segment=STOCK_UNDERLYING_SEGMENT,
        )
        atm = find_atm_row(chain_df, spot)

        security_id_key = f"{option_side.lower()}_security_id"
        ltp_key = f"{option_side.lower()}_ltp"
        option_security_id = atm[security_id_key]
        option_ltp = atm[ltp_key]

        if not option_security_id:
            raise ValueError(f"No {option_side} at ATM strike {atm['strike']} for {mover.symbol}")
        if option_ltp is None or float(option_ltp) <= 0:
            raise ValueError(f"Invalid LTP for {mover.symbol} {option_side} at strike {atm['strike']}")

        lot_size = get_lot_size(underlying=mover.symbol) or get_lot_size(security_id=str(option_security_id))
        if not lot_size:
            raise ValueError(f"Could not resolve lot size for {mover.symbol}")

        entry_price = float(option_ltp)
        target_price, stop_loss_price = calc_exit_prices(
            entry_price,
            target_pct=config.target_pct,
            stop_loss_pct=config.stop_loss_pct,
        )

        return PreparedOrder(
            trading_symbol=f"{mover.symbol} {int(atm['strike'])} {option_side}",
            symbol=mover.symbol,
            security_id=str(option_security_id),
            entry_price=entry_price,
            quantity=lot_size * config.lots,
            lot_size=lot_size,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            trailing_jump=config.trailing_jump,
            extra={
                "underlying_security_id": underlying_security_id,
                "option_side": option_side,
                "expiry": expiry,
                "spot": spot,
                "atm_strike": float(atm["strike"]),
                "mover_rank": mover.rank,
                "mover_change_pct": mover.per_change,
                "mover_ltp": mover.ltp,
                "direction": config.direction,
            },
        )

    def format_summary(self, order: PreparedOrder, config: TopMoverConfig) -> str:
        extra = order.extra
        lines = [
            "=== Top Mover Options Strategy ===",
            f"Instance:     {config.name}",
            f"Signal:       NSE F&O {config.direction} rank #{extra.get('mover_rank')}",
            f"Stock:        {order.symbol}",
            f"Change:       {extra.get('mover_change_pct', 0):+.2f}%",
            f"Spot:         Rs. {extra.get('spot', 0):,.2f}",
            f"Expiry:       {extra.get('expiry')}",
            f"ATM Strike:   {extra.get('atm_strike', 0):,.2f}",
            f"Option:       {extra.get('option_side')} (buy only)",
            f"Contract ID:  {order.security_id}",
            f"Entry:        Rs. {order.entry_price:,.2f}",
            f"Lots:         {config.lots} x {order.lot_size} = {order.quantity} qty",
        ]
        if order.target_price is not None:
            lines.append(f"Target:       Rs. {order.target_price:,.2f} ({config.target_pct}%)")
        if order.stop_loss_price is not None:
            lines.append(f"Stop Loss:    Rs. {order.stop_loss_price:,.2f} ({config.stop_loss_pct}%)")
        if order.trailing_jump:
            lines.append(f"Trailing:     Rs. {order.trailing_jump:,.2f}")
        lines.append("==================================")
        return "\n".join(lines)

    def place_order(self, dhan_client, order: PreparedOrder, config: TopMoverConfig) -> dict:
        validation = validate_order(
            security_id=order.security_id,
            exchange_segment=dhanhq.NSE_FNO,
            transaction_type=dhanhq.BUY,
            quantity=order.quantity,
            order_type=config.order_type,
            product_type=config.product,
            price=order.entry_price,
            trading_symbol=order.trading_symbol,
            lot_size=order.lot_size,
        )
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))

        margin = check_margin(
            dhan_client,
            security_id=order.security_id,
            exchange_segment=dhanhq.NSE_FNO,
            transaction_type=dhanhq.BUY,
            quantity=order.quantity,
            product_type=config.product,
            price=order.entry_price,
        )
        if not margin["sufficient"]:
            raise ValueError(
                f"Insufficient margin: need Rs. {margin['total_margin']:,.2f}, "
                f"available Rs. {margin['available_balance']:,.2f}"
            )

        tag = f"top_mover_{order.symbol}_{order.extra.get('option_side', '').lower()}"
        if self.uses_super_order(config):
            return dhan_client.place_super_order(
                security_id=order.security_id,
                exchange_segment=dhanhq.NSE_FNO,
                transaction_type=dhanhq.BUY,
                quantity=order.quantity,
                order_type=config.order_type,
                product_type=config.product,
                price=order.entry_price,
                targetPrice=order.target_price or 0.0,
                stopLossPrice=order.stop_loss_price or 0.0,
                trailingJump=order.trailing_jump,
                tag=tag,
            )

        return dhan_client.place_order(
            security_id=order.security_id,
            exchange_segment=dhanhq.NSE_FNO,
            transaction_type=dhanhq.BUY,
            quantity=order.quantity,
            order_type=config.order_type,
            product_type=config.product,
            price=order.entry_price,
            validity=dhanhq.DAY,
            tag=tag,
        )

    def uses_super_order(self, config: TopMoverConfig) -> bool:
        return config.target_pct is not None or config.stop_loss_pct is not None

    def monitor_poll_sec(self, config: TopMoverConfig) -> int:
        return config.monitor_poll_sec
