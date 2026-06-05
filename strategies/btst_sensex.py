"""BTST Sensex strategy — placeholder for future implementation."""

from __future__ import annotations

from dataclasses import dataclass

from strategies.base import BaseStrategy, PreparedOrder


@dataclass(frozen=True)
class BtstSensexConfig:
    name: str
    lots: int = 1
    run_at: str | None = None


class BtstSensexStrategy(BaseStrategy):
    strategy_type = "btst_sensex"

    def parse_config(self, raw: dict, name: str) -> BtstSensexConfig:
        return BtstSensexConfig(
            name=name,
            lots=int(raw.get("lots", 1)),
            run_at=raw.get("run_at"),
        )

    def prepare(self, dhan_client, config: BtstSensexConfig, *, skip_wait: bool = False) -> PreparedOrder:
        raise NotImplementedError("btst_sensex strategy is not implemented yet")

    def format_summary(self, order: PreparedOrder, config: BtstSensexConfig) -> str:
        return "BTST Sensex — not implemented"

    def place_order(self, dhan_client, order: PreparedOrder, config: BtstSensexConfig) -> dict:
        raise NotImplementedError("btst_sensex strategy is not implemented yet")
