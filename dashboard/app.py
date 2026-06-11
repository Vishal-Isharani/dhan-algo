"""FastAPI dashboard — configure strategies, view reports, export trades."""

from __future__ import annotations

import io
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from scripts.config_store import (
    list_strategies_with_config,
    set_enabled,
    update_config,
)
from scripts.dhan_helpers import get_client
from scripts.strategy_loader import load_strategy_runs
from scripts.trade_journal import export_trades_csv, get_open_trades, list_trades, summary_stats
from scripts.trade_reconcile import reconcile_open_trades
from scripts.trading_calendar import is_trading_day
from strategies.registry import list_strategy_types

IST = ZoneInfo("Asia/Kolkata")
STATIC_DIR = Path(__file__).parent / "static"
STATE_FILE = Path("data/scheduler_state.json")


class ConfigUpdate(BaseModel):
    config: dict


class EnabledUpdate(BaseModel):
    enabled: bool


def _check_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("DASHBOARD_API_KEY", "").strip()
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


app = FastAPI(title="dhan-algo Dashboard", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(IST).isoformat()}


@app.get("/api/strategy-types", dependencies=[Depends(_check_api_key)])
def strategy_types() -> dict:
    return {"types": list_strategy_types()}


@app.get("/api/strategies", dependencies=[Depends(_check_api_key)])
def strategies() -> dict:
    return {"strategies": list_strategies_with_config()}


@app.patch("/api/strategies/{name}", dependencies=[Depends(_check_api_key)])
def toggle_strategy(name: str, body: EnabledUpdate) -> dict:
    try:
        entry = set_enabled(name, body.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "strategy": entry}


@app.put("/api/strategies/{name}/config", dependencies=[Depends(_check_api_key)])
def save_strategy_config(name: str, body: ConfigUpdate) -> dict:
    try:
        config = update_config(name, body.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "config": config}


@app.get("/api/reports/summary", dependencies=[Depends(_check_api_key)])
def report_summary(
    strategy: str | None = Query(default=None),
    strategy_type: str | None = Query(default=None, alias="type"),
) -> dict:
    return summary_stats(strategy_name=strategy, strategy_type=strategy_type)


@app.get("/api/reports/trades", dependencies=[Depends(_check_api_key)])
def report_trades(
    strategy: str | None = Query(default=None),
    strategy_type: str | None = Query(default=None, alias="type"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    trades = list_trades(
        strategy_name=strategy,
        strategy_type=strategy_type,
        limit=limit,
    )
    return {"trades": trades, "count": len(trades)}


@app.get("/api/reports/open", dependencies=[Depends(_check_api_key)])
def open_trades(
    strategy: str | None = Query(default=None),
    strategy_type: str | None = Query(default=None, alias="type"),
) -> dict:
    trades = get_open_trades(strategy_name=strategy, strategy_type=strategy_type)
    return {"trades": trades, "count": len(trades)}


@app.post("/api/reports/sync", dependencies=[Depends(_check_api_key)])
def sync_trades(
    strategy: str | None = Query(default=None),
    strategy_type: str | None = Query(default=None, alias="type"),
) -> dict:
    try:
        dhan, _ = get_client()
        results = reconcile_open_trades(
            dhan,
            strategy_name=strategy,
            strategy_type=strategy_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Dhan sync failed: {exc}") from exc

    return {
        "ok": True,
        "synced": len(results),
        "results": results,
        "message": (
            f"Synced {len(results)} trade(s) from Dhan."
            if results
            else "No open trades needed syncing."
        ),
    }


@app.get("/api/reports/export", dependencies=[Depends(_check_api_key)])
def export_csv(
    strategy: str | None = Query(default=None),
    strategy_type: str | None = Query(default=None, alias="type"),
) -> StreamingResponse:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        count = export_trades_csv(
            tmp_path,
            strategy_name=strategy,
            strategy_type=strategy_type,
        )
        content = Path(tmp_path).read_text(encoding="utf-8")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    label = strategy or strategy_type or "all"
    filename = f"trades_{label}_{datetime.now(IST).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/scheduler/status", dependencies=[Depends(_check_api_key)])
def scheduler_status() -> dict:
    today = datetime.now(IST).date()
    state: dict = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    scheduled: list[dict] = []
    try:
        for run in load_strategy_runs():
            run_at = getattr(run.config, "run_at", None)
            scheduled.append({
                "name": run.name,
                "type": run.strategy_type,
                "run_at": run_at,
            })
    except ValueError:
        pass

    all_entries = list_strategies_with_config()
    return {
        "today": today.isoformat(),
        "is_trading_day": is_trading_day(today),
        "scheduler_state": state,
        "enabled_strategies": scheduled,
        "all_strategies": [
            {"name": s["name"], "type": s["type"], "enabled": s["enabled"], "run_at": (s.get("config") or {}).get("run_at")}
            for s in all_entries
        ],
    }


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
