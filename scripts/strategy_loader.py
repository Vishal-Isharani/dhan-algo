"""Load strategy instances from manifest (runtime data/ or baked-in strategies/)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.config_store import load_manifest, resolve_config_path
from strategies.base import StrategyRun
from strategies.registry import get_strategy

LEGACY_STRATEGY_FILE = Path("strategy.json")


def load_strategy_runs(names: list[str] | None = None) -> list[StrategyRun]:
    entries = load_manifest()
    loaded: list[StrategyRun] = []

    for entry in entries:
        name = entry.get("name")
        strategy_type = entry.get("type")
        if not name or not strategy_type:
            continue
        if names and name not in names:
            continue
        if not entry.get("enabled", True):
            continue

        config_file = entry.get("config", f"{name}.json")
        path = resolve_config_path(config_file)
        if not path.exists() and LEGACY_STRATEGY_FILE.exists() and name == "default":
            path = LEGACY_STRATEGY_FILE

        if not path.exists():
            raise FileNotFoundError(f"Config not found for '{name}': {config_file}")

        raw = json.loads(path.read_text(encoding="utf-8"))
        strategy = get_strategy(strategy_type)
        config = strategy.parse_config(raw, name)
        loaded.append(StrategyRun(name=name, strategy_type=strategy_type, config=config))

    if names:
        found = {run.name for run in loaded}
        missing = [name for name in names if name not in found]
        if missing:
            raise ValueError(f"Unknown or disabled strategy instances: {', '.join(missing)}")

    if not loaded:
        raise ValueError("No enabled strategies to run")

    return loaded
