"""Base types and interface for all trading strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PreparedOrder:
    trading_symbol: str
    symbol: str
    security_id: str
    entry_price: float
    quantity: int
    lot_size: int
    target_price: float | None = None
    stop_loss_price: float | None = None
    trailing_jump: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyRun:
    name: str
    strategy_type: str
    config: Any

    def to_dict(self) -> dict:
        config_dict = asdict(self.config) if hasattr(self.config, "__dataclass_fields__") else self.config
        return {
            "name": self.name,
            "type": self.strategy_type,
            "config": config_dict,
        }


class BaseStrategy(ABC):
    strategy_type: str

    @abstractmethod
    def parse_config(self, raw: dict, name: str) -> Any:
        """Parse a strategy-specific config file."""

    @abstractmethod
    def prepare(self, dhan_client, config: Any, *, skip_wait: bool = False) -> PreparedOrder:
        """Build the order from market data."""

    @abstractmethod
    def format_summary(self, order: PreparedOrder, config: Any) -> str:
        """Human-readable pre-trade summary."""

    @abstractmethod
    def place_order(self, dhan_client, order: PreparedOrder, config: Any) -> dict:
        """Place the live order."""

    def uses_super_order(self, config: Any) -> bool:
        return False

    def monitor_poll_sec(self, config: Any) -> int:
        return 30

    def lots(self, config: Any) -> int:
        return getattr(config, "lots", 1)
