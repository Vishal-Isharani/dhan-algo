"""Persist trades for later analysis."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from strategies.base import PreparedOrder

IST = ZoneInfo("Asia/Kolkata")
DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "trades.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    strategy_type TEXT NOT NULL,
    strategy_config TEXT NOT NULL,
    status TEXT NOT NULL,

    symbol TEXT,
    option_side TEXT,
    strike REAL,
    expiry TEXT,
    security_id TEXT,
    trading_symbol TEXT,

    direction TEXT,
    mover_rank INTEGER,
    mover_change_pct REAL,
    spot REAL,

    entry_price REAL,
    target_price REAL,
    stop_loss_price REAL,
    exit_price REAL,
    quantity INTEGER,
    lot_size INTEGER,
    lots INTEGER,

    order_id TEXT,
    order_status TEXT,
    exit_reason TEXT,

    pnl REAL,
    pnl_pct REAL,
    notes TEXT
)
"""


def _now() -> str:
    return datetime.now(IST).isoformat()


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
    if "strategy_type" not in columns:
        conn.execute("ALTER TABLE trades ADD COLUMN strategy_type TEXT NOT NULL DEFAULT 'unknown'")
        conn.commit()
    return conn


def _calc_pnl(entry: float, exit_price: float | None, quantity: int) -> tuple[float | None, float | None]:
    if exit_price is None:
        return None, None
    pnl = round((exit_price - entry) * quantity, 2)
    pnl_pct = round(((exit_price - entry) / entry) * 100, 2) if entry else None
    return pnl, pnl_pct


def _fields_from_prepared(prepared: PreparedOrder | None) -> dict:
    if prepared is None:
        return {}
    extra = prepared.extra
    return {
        "symbol": prepared.symbol,
        "option_side": extra.get("option_side"),
        "strike": extra.get("atm_strike"),
        "expiry": extra.get("expiry"),
        "security_id": prepared.security_id,
        "trading_symbol": prepared.trading_symbol,
        "direction": extra.get("direction"),
        "mover_rank": extra.get("mover_rank"),
        "mover_change_pct": extra.get("mover_change_pct"),
        "spot": extra.get("spot"),
        "entry_price": prepared.entry_price,
        "target_price": prepared.target_price,
        "stop_loss_price": prepared.stop_loss_price,
        "quantity": prepared.quantity,
        "lot_size": prepared.lot_size,
    }


def log_trade_open(
    *,
    strategy_name: str,
    strategy_type: str,
    strategy_config: dict,
    prepared: PreparedOrder,
    order_id: str | None,
    order_status: str | None,
    lots: int,
) -> int:
    now = _now()
    fields = _fields_from_prepared(prepared)
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO trades (
                created_at, updated_at, strategy_name, strategy_type, strategy_config, status,
                symbol, option_side, strike, expiry, security_id, trading_symbol,
                direction, mover_rank, mover_change_pct, spot,
                entry_price, target_price, stop_loss_price, quantity, lot_size, lots,
                order_id, order_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                strategy_name,
                strategy_type,
                json.dumps(strategy_config),
                "open",
                fields.get("symbol"),
                fields.get("option_side"),
                fields.get("strike"),
                fields.get("expiry"),
                fields.get("security_id"),
                fields.get("trading_symbol"),
                fields.get("direction"),
                fields.get("mover_rank"),
                fields.get("mover_change_pct"),
                fields.get("spot"),
                fields.get("entry_price"),
                fields.get("target_price"),
                fields.get("stop_loss_price"),
                fields.get("quantity"),
                fields.get("lot_size"),
                lots,
                order_id,
                order_status,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def log_trade_failed(
    *,
    strategy_name: str,
    strategy_type: str,
    strategy_config: dict,
    reason: str,
    prepared: PreparedOrder | None = None,
) -> int:
    now = _now()
    fields = _fields_from_prepared(prepared)
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO trades (
                created_at, updated_at, strategy_name, strategy_type, strategy_config, status,
                symbol, option_side, strike, expiry, security_id, trading_symbol,
                direction, mover_rank, mover_change_pct, spot,
                entry_price, target_price, stop_loss_price, quantity, lot_size, lots,
                exit_reason, notes, pnl, pnl_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                strategy_name,
                strategy_type,
                json.dumps(strategy_config),
                "failed",
                fields.get("symbol"),
                fields.get("option_side"),
                fields.get("strike"),
                fields.get("expiry"),
                fields.get("security_id"),
                fields.get("trading_symbol"),
                fields.get("direction"),
                fields.get("mover_rank"),
                fields.get("mover_change_pct"),
                fields.get("spot"),
                fields.get("entry_price"),
                fields.get("target_price"),
                fields.get("stop_loss_price"),
                fields.get("quantity"),
                fields.get("lot_size"),
                strategy_config.get("config", {}).get("lots"),
                reason,
                reason,
                0.0,
                0.0,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def update_trade_exit(
    trade_id: int,
    *,
    exit_reason: str,
    exit_price: float | None,
    status: str,
    notes: str = "",
) -> None:
    now = _now()
    with _connect() as conn:
        row = conn.execute("SELECT entry_price, quantity FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            return

        pnl, pnl_pct = _calc_pnl(float(row["entry_price"]), exit_price, int(row["quantity"]))
        conn.execute(
            """
            UPDATE trades
            SET updated_at = ?, status = ?, exit_reason = ?, exit_price = ?,
                pnl = ?, pnl_pct = ?, notes = ?
            WHERE id = ?
            """,
            (now, status, exit_reason, exit_price, pnl, pnl_pct, notes, trade_id),
        )
        conn.commit()


def list_trades(
    *,
    strategy_name: str | None = None,
    strategy_type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    query = "SELECT * FROM trades"
    filters: list[str] = []
    params: list = []
    if strategy_name:
        filters.append("strategy_name = ?")
        params.append(strategy_name)
    if strategy_type:
        filters.append("strategy_type = ?")
        params.append(strategy_type)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def summary_stats(
    *,
    strategy_name: str | None = None,
    strategy_type: str | None = None,
) -> dict:
    query = """
        SELECT
            COUNT(*) AS total_trades,
            SUM(CASE WHEN status IN ('target', 'stop_loss', 'closed') THEN 1 ELSE 0 END) AS closed_trades,
            SUM(CASE WHEN status = 'target' THEN 1 ELSE 0 END) AS targets,
            SUM(CASE WHEN status = 'stop_loss' THEN 1 ELSE 0 END) AS stop_losses,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failures,
            ROUND(SUM(COALESCE(pnl, 0)), 2) AS total_pnl,
            ROUND(AVG(CASE WHEN pnl IS NOT NULL THEN pnl END), 2) AS avg_pnl
        FROM trades
    """
    filters: list[str] = []
    params: list = []
    if strategy_name:
        filters.append("strategy_name = ?")
        params.append(strategy_name)
    if strategy_type:
        filters.append("strategy_type = ?")
        params.append(strategy_type)
    if filters:
        query += " WHERE " + " AND ".join(filters)

    with _connect() as conn:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else {}
