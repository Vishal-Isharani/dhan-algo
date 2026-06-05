"""Load strategy instances from manifest.json."""

from __future__ import annotations

import json
from pathlib import Path

from strategies.base import StrategyRun
from strategies.registry import get_strategy

STRATEGIES_DIR = Path("strategies")
CONFIGS_DIR = STRATEGIES_DIR / "configs"
MANIFEST_FILE = STRATEGIES_DIR / "manifest.json"
LEGACY_STRATEGY_FILE = Path("strategy.json")


def _resolve_config_path(config_file: str) -> Path:
    path = Path(config_file)
    if not path.is_absolute() and not path.exists():
        path = CONFIGS_DIR / config_file
    return path


def load_manifest() -> list[dict]:
    if MANIFEST_FILE.exists():
        manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        return manifest.get("strategies", [])

    if LEGACY_STRATEGY_FILE.exists():
        return [{
            "name": "default",
            "type": "top_mover_options",
            "config": str(LEGACY_STRATEGY_FILE),
            "enabled": True,
        }]

    raise FileNotFoundError(
        "No strategies found. Copy strategies/manifest.example.json to "
        "strategies/manifest.json and add configs under strategies/configs/."
    )


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
        path = _resolve_config_path(config_file)
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
