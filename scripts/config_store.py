"""Runtime strategy config in data/ — survives redeploys via volume mount."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from strategies.registry import get_strategy

BUILTIN_STRATEGIES_DIR = Path("strategies")
BUILTIN_CONFIGS_DIR = BUILTIN_STRATEGIES_DIR / "configs"
BUILTIN_MANIFEST = BUILTIN_STRATEGIES_DIR / "manifest.json"
LEGACY_STRATEGY_FILE = Path("strategy.json")

RUNTIME_DIR = Path("data") / "strategy_config"
RUNTIME_CONFIGS_DIR = RUNTIME_DIR / "configs"
RUNTIME_MANIFEST = RUNTIME_DIR / "manifest.json"


def _ensure_runtime() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    if not RUNTIME_MANIFEST.exists():
        if BUILTIN_MANIFEST.exists():
            shutil.copy2(BUILTIN_MANIFEST, RUNTIME_MANIFEST)
        elif LEGACY_STRATEGY_FILE.exists():
            legacy = {
                "strategies": [{
                    "name": "default",
                    "type": "top_mover_options",
                    "config": str(LEGACY_STRATEGY_FILE),
                    "enabled": True,
                }]
            }
            RUNTIME_MANIFEST.write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")

    if BUILTIN_CONFIGS_DIR.exists():
        for source in BUILTIN_CONFIGS_DIR.glob("*.json"):
            dest = RUNTIME_CONFIGS_DIR / source.name
            if not dest.exists():
                shutil.copy2(source, dest)


def _read_manifest_raw() -> dict:
    _ensure_runtime()
    if not RUNTIME_MANIFEST.exists():
        raise FileNotFoundError(
            "No strategies found. Copy strategies/manifest.example.json to "
            "strategies/manifest.json and add configs under strategies/configs/."
        )
    return json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))


def _write_manifest_raw(data: dict) -> None:
    _ensure_runtime()
    RUNTIME_MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_manifest() -> list[dict]:
    return _read_manifest_raw().get("strategies", [])


def save_manifest(strategies: list[dict]) -> None:
    _write_manifest_raw({"strategies": strategies})


def _find_entry(name: str) -> dict:
    for entry in load_manifest():
        if entry.get("name") == name:
            return entry
    raise KeyError(f"Unknown strategy instance: {name}")


def resolve_config_path(config_file: str) -> Path:
    _ensure_runtime()
    path = Path(config_file)
    if path.is_absolute():
        return path
    runtime = RUNTIME_CONFIGS_DIR / config_file
    if runtime.exists():
        return runtime
    builtin = BUILTIN_CONFIGS_DIR / config_file
    if builtin.exists():
        return builtin
    if path.exists():
        return path
    return runtime


def read_config(config_file: str) -> dict:
    path = resolve_config_path(config_file)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {config_file}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_config(config_file: str, config: dict) -> None:
    _ensure_runtime()
    path = RUNTIME_CONFIGS_DIR / Path(config_file).name
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def list_strategies_with_config() -> list[dict]:
    """All manifest entries with their config payload and validation status."""

    results: list[dict] = []
    for entry in load_manifest():
        name = entry.get("name")
        strategy_type = entry.get("type")
        config_file = entry.get("config", f"{name}.json")
        item = {
            "name": name,
            "type": strategy_type,
            "config_file": config_file,
            "enabled": entry.get("enabled", True),
            "config": None,
            "valid": True,
            "error": None,
        }
        if not name or not strategy_type:
            item["valid"] = False
            item["error"] = "Missing name or type"
            results.append(item)
            continue
        try:
            raw = read_config(config_file)
            strategy = get_strategy(strategy_type)
            strategy.parse_config(raw, name)
            item["config"] = raw
        except Exception as exc:
            item["valid"] = False
            item["error"] = str(exc)
            try:
                item["config"] = read_config(config_file)
            except Exception:
                pass
        results.append(item)
    return results


def set_enabled(name: str, enabled: bool) -> dict:
    strategies = load_manifest()
    updated = None
    for entry in strategies:
        if entry.get("name") == name:
            entry["enabled"] = enabled
            updated = entry
            break
    if updated is None:
        raise KeyError(f"Unknown strategy instance: {name}")
    save_manifest(strategies)
    return updated


def update_config(name: str, config: dict) -> dict:
    entry = _find_entry(name)
    strategy_type = entry.get("type")
    if not strategy_type:
        raise ValueError(f"{name}: missing strategy type")

    strategy = get_strategy(strategy_type)
    strategy.parse_config(config, name)

    config_file = entry.get("config", f"{name}.json")
    write_config(config_file, config)
    return config
