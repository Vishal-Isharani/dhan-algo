"""Registry of available strategy implementations."""

from __future__ import annotations

from strategies.base import BaseStrategy
from strategies.btst_nifty import BtstNiftyStrategy
from strategies.btst_sensex import BtstSensexStrategy
from strategies.top_mover_options import TopMoverOptionsStrategy

_REGISTRY: dict[str, BaseStrategy] = {
    TopMoverOptionsStrategy.strategy_type: TopMoverOptionsStrategy(),
    BtstNiftyStrategy.strategy_type: BtstNiftyStrategy(),
    BtstSensexStrategy.strategy_type: BtstSensexStrategy(),
}


def get_strategy(strategy_type: str) -> BaseStrategy:
    try:
        return _REGISTRY[strategy_type]
    except KeyError as exc:
        available = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"Unknown strategy type '{strategy_type}'. Available: {available}") from exc


def list_strategy_types() -> list[str]:
    return sorted(_REGISTRY)
