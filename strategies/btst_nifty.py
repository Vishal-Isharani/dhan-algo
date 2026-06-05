"""BTST Nifty strategy — placeholder for future implementation."""

from __future__ import annotations

from dataclasses import dataclass

from strategies.base import BaseStrategy, PreparedOrder


@dataclass(frozen=True)
class BtstNiftyConfig:
    name: str
    lots: int = 1
    run_at: str | None = None


class BtstNiftyStrategy(BaseStrategy):
    strategy_type = "btst_nifty"

    def parse_config(self, raw: dict, name: str) -> BtstNiftyConfig:
        return BtstNiftyConfig(
            name=name,
            lots=int(raw.get("lots", 1)),
            run_at=raw.get("run_at"),
        )

    def prepare(self, dhan_client, config: BtstNiftyConfig, *, skip_wait: bool = False) -> PreparedOrder:
        raise NotImplementedError("btst_nifty strategy is not implemented yet")

    def format_summary(self, order: PreparedOrder, config: BtstNiftyConfig) -> str:
        return "BTST Nifty — not implemented"

    def place_order(self, dhan_client, order: PreparedOrder, config: BtstNiftyConfig) -> dict:
        raise NotImplementedError("btst_nifty strategy is not implemented yet")
