"""BTST Nifty — buy ATM weekly option near close, exit next morning."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from dhanhq import dhanhq

from scripts.dhan_helpers import (
    check_margin,
    fetch_chain_df,
    find_atm_row,
    get_lot_size,
    parse_expiry_list,
    unwrap_sdk_data,
)
from scripts.nse_client import NSEClient
from scripts.trading_calendar import can_btst_entry_today
from scripts.validate_order import validate_order
from strategies.base import BaseStrategy, PreparedOrder, StrategySkipped
from strategies.common import IST, wait_until_run_time

NIFTY_SECURITY_ID = 13
NIFTY_UNDERLYING_SEGMENT = "IDX_I"
OPTION_CHAIN_RATE_LIMIT_SEC = 3

TrendDirection = Literal["bullish", "bearish"]
OptionSide = Literal["CE", "PE"]


@dataclass(frozen=True)
class BtstNiftyConfig:
    name: str
    lots: int = 1
    run_at: str | None = "15:20"
    min_day_change_pct: float = 0.5
    max_vix: float = 18.0
    preopen_confirm_pct: float = 0.2
    exit_check_at: str = "09:13"
    exit_early_at: str = "09:15"
    exit_late_at: str = "09:20"
    product: str = "MARGIN"
    order_type: str = "MARKET"


def _parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _pick_weekly_expiry(expiries: list[str], today: date) -> str:
    weekly = sorted(e for e in expiries if _parse_date(e).weekday() == 3)
    if not weekly:
        return expiries[0]

    if today.weekday() == 3:
        future = [e for e in weekly if _parse_date(e) > today]
    else:
        future = [e for e in weekly if _parse_date(e) >= today]
    return future[0] if future else weekly[-1]


def _trend_from_closes(closes: list[float]) -> TrendDirection | None:
    if len(closes) < 2:
        return None
    ascending = all(closes[i] < closes[i + 1] for i in range(len(closes) - 1))
    descending = all(closes[i] > closes[i + 1] for i in range(len(closes) - 1))
    if ascending:
        return "bullish"
    if descending:
        return "bearish"
    return None


def _day_trend(percent_change: float) -> TrendDirection | None:
    if percent_change > 0:
        return "bullish"
    if percent_change < 0:
        return "bearish"
    return None


def _trend_to_option_side(trend: TrendDirection) -> OptionSide:
    return "CE" if trend == "bullish" else "PE"


class BtstNiftyStrategy(BaseStrategy):
    strategy_type = "btst_nifty"

    def parse_config(self, raw: dict, name: str) -> BtstNiftyConfig:
        lots = int(raw.get("lots", 1))
        if lots < 1:
            raise ValueError(f"{name}: lots must be at least 1")

        return BtstNiftyConfig(
            name=name,
            lots=lots,
            run_at=raw.get("run_at", "15:20"),
            min_day_change_pct=float(raw.get("min_day_change_pct", 0.5)),
            max_vix=float(raw.get("max_vix", 18.0)),
            preopen_confirm_pct=float(raw.get("preopen_confirm_pct", 0.2)),
            exit_check_at=raw.get("exit_check_at", "09:13"),
            exit_early_at=raw.get("exit_early_at", "09:15"),
            exit_late_at=raw.get("exit_late_at", "09:20"),
            product=raw.get("product", "MARGIN"),
            order_type=raw.get("order_type", "MARKET"),
        )

    def _fetch_last_twenty_min_closes(self, dhan_client, today: date) -> list[float]:
        start = datetime(today.year, today.month, today.day, 15, 0, tzinfo=IST)
        end = datetime(today.year, today.month, today.day, 15, 20, tzinfo=IST)
        response = dhan_client.intraday_minute_data(
            security_id=str(NIFTY_SECURITY_ID),
            exchange_segment=dhanhq.INDEX,
            instrument_type="INDEX",
            from_date=start.strftime("%Y-%m-%d %H:%M:%S"),
            to_date=end.strftime("%Y-%m-%d %H:%M:%S"),
            interval=5,
        )
        payload = unwrap_sdk_data(response)
        timestamps = payload.get("timestamp") or []
        closes = payload.get("close") or []
        if not timestamps or not closes:
            raise StrategySkipped("No 5-min Nifty candles for 15:00–15:20 window")

        candles: list[tuple[datetime, float]] = []
        for ts, close in zip(timestamps, closes, strict=False):
            candle_time = dhan_client.convert_to_date_time(ts)
            if candle_time.tzinfo is None:
                candle_time = candle_time.replace(tzinfo=IST)
            else:
                candle_time = candle_time.astimezone(IST)
            candles.append((candle_time, float(close)))

        candles.sort(key=lambda item: item[0])
        window = [
            close
            for candle_time, close in candles
            if start <= candle_time <= end
        ]
        if len(window) < 4:
            raise StrategySkipped(
                f"Need 4 five-minute closes in 15:00–15:20 window, got {len(window)}"
            )
        return window[-4:]

    def _evaluate_entry(self, dhan_client, config: BtstNiftyConfig) -> tuple[TrendDirection, dict]:
        today = datetime.now(IST).date()

        allowed, reason = can_btst_entry_today(today)
        if not allowed:
            raise StrategySkipped(reason)

        nse = NSEClient()
        nifty = nse.get_nifty_quote()
        day_change = abs(nifty["percent_change"])
        if day_change < config.min_day_change_pct:
            raise StrategySkipped(
                f"|Nifty day change| {day_change:.2f}% < {config.min_day_change_pct}%"
            )

        vix = nse.get_india_vix()
        if vix > config.max_vix:
            raise StrategySkipped(f"India VIX {vix:.2f} > {config.max_vix}")

        closes = self._fetch_last_twenty_min_closes(dhan_client, today)
        candle_trend = _trend_from_closes(closes)
        if candle_trend is None:
            raise StrategySkipped(f"Last 4 closes not strictly mono: {closes}")

        day_trend = _day_trend(nifty["percent_change"])
        if day_trend is None or day_trend != candle_trend:
            raise StrategySkipped(
                f"Day trend ({day_trend}) != candle trend ({candle_trend}); "
                f"day {nifty['percent_change']:+.2f}%"
            )

        signal = {
            "trend": candle_trend,
            "day_change_pct": nifty["percent_change"],
            "nifty_last": nifty["last"],
            "nifty_prev_close": nifty["previous_close"],
            "india_vix": vix,
            "last_4_closes": closes,
            "btst_reason": reason,
        }
        return candle_trend, signal

    def prepare(self, dhan_client, config: BtstNiftyConfig, *, skip_wait: bool = False) -> PreparedOrder:
        if not skip_wait:
            wait_until_run_time(config.run_at)

        trend, signal = self._evaluate_entry(dhan_client, config)
        option_side = _trend_to_option_side(trend)
        today = datetime.now(IST).date()

        expiry_response = dhan_client.expiry_list(
            under_security_id=NIFTY_SECURITY_ID,
            under_exchange_segment=NIFTY_UNDERLYING_SEGMENT,
        )
        expiries = parse_expiry_list(expiry_response)
        if not expiries:
            raise ValueError("No Nifty option expiries found")
        expiry = _pick_weekly_expiry(expiries, today)

        time.sleep(OPTION_CHAIN_RATE_LIMIT_SEC)
        chain_df, spot = fetch_chain_df(
            dhan_client,
            under_security_id=NIFTY_SECURITY_ID,
            expiry=expiry,
            under_exchange_segment=NIFTY_UNDERLYING_SEGMENT,
        )
        atm = find_atm_row(chain_df, spot)

        security_id_key = f"{option_side.lower()}_security_id"
        ltp_key = f"{option_side.lower()}_ltp"
        option_security_id = atm[security_id_key]
        option_ltp = atm[ltp_key]

        if not option_security_id:
            raise ValueError(f"No {option_side} at ATM strike {atm['strike']}")
        if option_ltp is None or float(option_ltp) <= 0:
            raise ValueError(f"Invalid LTP for Nifty {option_side} at strike {atm['strike']}")

        lot_size = get_lot_size(underlying="NIFTY") or get_lot_size(security_id=str(option_security_id))
        if not lot_size:
            raise ValueError("Could not resolve Nifty lot size")

        entry_price = float(option_ltp) if config.order_type == "MARKET" else round(float(option_ltp) * 1.015, 1)

        return PreparedOrder(
            trading_symbol=f"NIFTY {int(atm['strike'])} {option_side}",
            symbol="NIFTY",
            security_id=str(option_security_id),
            entry_price=entry_price,
            quantity=lot_size * config.lots,
            lot_size=lot_size,
            extra={
                "underlying_security_id": str(NIFTY_SECURITY_ID),
                "option_side": option_side,
                "expiry": expiry,
                "spot": spot,
                "atm_strike": float(atm["strike"]),
                "direction": trend,
                "day_change_pct": signal["day_change_pct"],
                "india_vix": signal["india_vix"],
                "last_4_closes": signal["last_4_closes"],
                "nifty_last": signal["nifty_last"],
                "exit_check_at": config.exit_check_at,
                "exit_early_at": config.exit_early_at,
                "exit_late_at": config.exit_late_at,
                "preopen_confirm_pct": config.preopen_confirm_pct,
            },
        )

    def format_summary(self, order: PreparedOrder, config: BtstNiftyConfig) -> str:
        extra = order.extra
        lines = [
            "=== BTST Nifty Strategy ===",
            f"Instance:     {config.name}",
            f"Trend:        {extra.get('direction')} -> buy {extra.get('option_side')}",
            f"Nifty move:   {extra.get('day_change_pct', 0):+.2f}%",
            f"India VIX:    {extra.get('india_vix', 0):.2f}",
            f"Last 4 closes:{extra.get('last_4_closes')}",
            f"Spot:         Rs. {extra.get('spot', 0):,.2f}",
            f"Expiry:       {extra.get('expiry')}",
            f"ATM Strike:   {extra.get('atm_strike', 0):,.0f}",
            f"Contract ID:  {order.security_id}",
            f"Entry:        {config.order_type} @ Rs. {order.entry_price:,.2f}",
            f"Product:      {config.product} (carryforward)",
            f"Lots:         {config.lots} x {order.lot_size} = {order.quantity} qty",
            f"Exit plan:    check {extra.get('exit_check_at')}, "
            f"early {extra.get('exit_early_at')}, late {extra.get('exit_late_at')}",
            "===========================",
        ]
        return "\n".join(lines)

    def place_order(self, dhan_client, order: PreparedOrder, config: BtstNiftyConfig) -> dict:
        price = 0.0 if config.order_type == "MARKET" else order.entry_price
        validation = validate_order(
            security_id=order.security_id,
            exchange_segment=dhanhq.NSE_FNO,
            transaction_type=dhanhq.BUY,
            quantity=order.quantity,
            order_type=config.order_type,
            product_type=config.product,
            price=price or order.entry_price,
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

        return dhan_client.place_order(
            security_id=order.security_id,
            exchange_segment=dhanhq.NSE_FNO,
            transaction_type=dhanhq.BUY,
            quantity=order.quantity,
            order_type=config.order_type,
            product_type=config.product,
            price=price,
            validity=dhanhq.DAY,
            tag=f"btst_nifty_{order.extra.get('option_side', '').lower()}",
        )

    def is_btst(self, config: BtstNiftyConfig) -> bool:
        return True
