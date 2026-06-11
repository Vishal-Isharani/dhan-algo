"""Persist trades for later analysis."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import date, datetime, timedelta
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
    underlying_security_id TEXT,
    trading_symbol TEXT,

    direction TEXT,
    mover_rank INTEGER,
    mover_change_pct REAL,
    mover_ltp REAL,
    spot REAL,

    entry_price REAL,
    entry_fill_price REAL,
    target_price REAL,
    stop_loss_price REAL,
    exit_price REAL,
    exit_fill_price REAL,
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

MIGRATION_COLUMNS = {
    "strategy_type": "TEXT NOT NULL DEFAULT 'unknown'",
    "underlying_security_id": "TEXT",
    "mover_ltp": "REAL",
    "entry_fill_price": "REAL",
    "exit_fill_price": "REAL",
}


def _now() -> str:
    return datetime.now(IST).isoformat()


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
    for column, definition in MIGRATION_COLUMNS.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {column} {definition}")
    conn.commit()
    return conn


def _effective_entry(entry_price: float | None, entry_fill_price: float | None) -> float | None:
    if entry_fill_price is not None:
        return entry_fill_price
    return entry_price


def _effective_exit(exit_price: float | None, exit_fill_price: float | None) -> float | None:
    if exit_fill_price is not None:
        return exit_fill_price
    return exit_price


def _calc_pnl(
    entry_price: float | None,
    exit_price: float | None,
    quantity: int,
    *,
    entry_fill_price: float | None = None,
    exit_fill_price: float | None = None,
) -> tuple[float | None, float | None]:
    entry = _effective_entry(entry_price, entry_fill_price)
    exit_val = _effective_exit(exit_price, exit_fill_price)
    if entry is None or exit_val is None:
        return None, None
    pnl = round((exit_val - entry) * quantity, 2)
    pnl_pct = round(((exit_val - entry) / entry) * 100, 2) if entry else None
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
        "underlying_security_id": extra.get("underlying_security_id"),
        "trading_symbol": prepared.trading_symbol,
        "direction": extra.get("direction"),
        "mover_rank": extra.get("mover_rank"),
        "mover_change_pct": extra.get("mover_change_pct"),
        "mover_ltp": extra.get("mover_ltp"),
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
    entry_fill_price: float | None = None,
) -> int:
    now = _now()
    fields = _fields_from_prepared(prepared)
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO trades (
                created_at, updated_at, strategy_name, strategy_type, strategy_config, status,
                symbol, option_side, strike, expiry, security_id, underlying_security_id,
                trading_symbol, direction, mover_rank, mover_change_pct, mover_ltp, spot,
                entry_price, entry_fill_price, target_price, stop_loss_price,
                quantity, lot_size, lots, order_id, order_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                fields.get("underlying_security_id"),
                fields.get("trading_symbol"),
                fields.get("direction"),
                fields.get("mover_rank"),
                fields.get("mover_change_pct"),
                fields.get("mover_ltp"),
                fields.get("spot"),
                fields.get("entry_price"),
                entry_fill_price,
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
                symbol, option_side, strike, expiry, security_id, underlying_security_id,
                trading_symbol, direction, mover_rank, mover_change_pct, mover_ltp, spot,
                entry_price, target_price, stop_loss_price, quantity, lot_size, lots,
                exit_reason, notes, pnl, pnl_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                fields.get("underlying_security_id"),
                fields.get("trading_symbol"),
                fields.get("direction"),
                fields.get("mover_rank"),
                fields.get("mover_change_pct"),
                fields.get("mover_ltp"),
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
    entry_fill_price: float | None = None,
    exit_fill_price: float | None = None,
) -> None:
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT entry_price, entry_fill_price, quantity FROM trades WHERE id = ?",
            (trade_id,),
        ).fetchone()
        if not row:
            return

        effective_entry_fill = entry_fill_price
        if effective_entry_fill is None and row["entry_fill_price"] is not None:
            effective_entry_fill = float(row["entry_fill_price"])

        pnl, pnl_pct = _calc_pnl(
            float(row["entry_price"]) if row["entry_price"] is not None else None,
            exit_price,
            int(row["quantity"]),
            entry_fill_price=effective_entry_fill,
            exit_fill_price=exit_fill_price,
        )
        conn.execute(
            """
            UPDATE trades
            SET updated_at = ?, status = ?, exit_reason = ?, exit_price = ?,
                entry_fill_price = COALESCE(?, entry_fill_price),
                exit_fill_price = ?, pnl = ?, pnl_pct = ?, notes = ?
            WHERE id = ?
            """,
            (
                now,
                status,
                exit_reason,
                exit_price,
                entry_fill_price,
                exit_fill_price,
                pnl,
                pnl_pct,
                notes,
                trade_id,
            ),
        )
        conn.commit()


def already_traded_today(strategy_name: str, day: date | None = None) -> bool:
    """True if a non-failed trade was logged for this strategy instance today."""

    day = day or datetime.now(IST).date()
    day_str = day.isoformat()
    rows = list_trades(strategy_name=strategy_name, limit=20)
    for row in rows:
        created_at = str(row.get("created_at") or "")
        if not created_at.startswith(day_str):
            continue
        if row.get("status") != "failed":
            return True
    return False


VALID_STATUSES = frozenset({"open", "target", "stop_loss", "closed", "failed"})
SORT_COLUMNS = {
    "id": "id",
    "date": "created_at",
    "created_at": "created_at",
    "strategy": "strategy_name",
    "strategy_name": "strategy_name",
    "symbol": "COALESCE(trading_symbol, symbol)",
    "status": "status",
    "pnl": "pnl",
    "entry": "COALESCE(entry_fill_price, entry_price)",
    "exit": "COALESCE(exit_fill_price, exit_price)",
}


def _parse_filter_date(value: str, *, end_of_day: bool = False) -> str:
    parsed = date.fromisoformat(value[:10])
    if end_of_day:
        return datetime(parsed.year, parsed.month, parsed.day, 23, 59, 59, tzinfo=IST).isoformat()
    return datetime(parsed.year, parsed.month, parsed.day, 0, 0, 0, tzinfo=IST).isoformat()


def _trade_filter_clauses(
    *,
    strategy_name: str | None = None,
    strategy_type: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[list[str], list]:
    clauses: list[str] = []
    params: list = []

    if strategy_name:
        clauses.append("strategy_name = ?")
        params.append(strategy_name)
    if strategy_type:
        clauses.append("strategy_type = ?")
        params.append(strategy_type)
    if status:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Allowed: {', '.join(sorted(VALID_STATUSES))}")
        clauses.append("status = ?")
        params.append(status)
    if date_from:
        clauses.append("created_at >= ?")
        params.append(_parse_filter_date(date_from))
    if date_to:
        clauses.append("created_at <= ?")
        params.append(_parse_filter_date(date_to, end_of_day=True))

    return clauses, params


def _resolve_sort(sort_by: str = "id", sort_order: str = "desc") -> str:
    column = SORT_COLUMNS.get(sort_by)
    if column is None:
        allowed = ", ".join(sorted(SORT_COLUMNS))
        raise ValueError(f"Invalid sort_by '{sort_by}'. Allowed: {allowed}")
    order = sort_order.lower()
    if order not in {"asc", "desc"}:
        raise ValueError("sort_order must be 'asc' or 'desc'")
    return f" ORDER BY {column} {order.upper()}"


def get_open_trades(
    *,
    strategy_name: str | None = None,
    strategy_type: str | None = None,
) -> list[dict]:
    """Return trades still marked open."""

    query = "SELECT * FROM trades WHERE status = 'open'"
    params: list = []
    if strategy_name:
        query += " AND strategy_name = ?"
        params.append(strategy_name)
    if strategy_type:
        query += " AND strategy_type = ?"
        params.append(strategy_type)
    query += " ORDER BY id ASC"

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def list_trades(
    *,
    strategy_name: str | None = None,
    strategy_type: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = "id",
    sort_order: str = "desc",
    limit: int | None = 50,
) -> list[dict]:
    query = "SELECT * FROM trades"
    filters, params = _trade_filter_clauses(
        strategy_name=strategy_name,
        strategy_type=strategy_type,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += _resolve_sort(sort_by, sort_order)
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def summary_stats(
    *,
    strategy_name: str | None = None,
    strategy_type: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    query = """
        SELECT
            COUNT(*) AS total_trades,
            SUM(CASE WHEN status IN ('target', 'stop_loss', 'closed') THEN 1 ELSE 0 END) AS closed_trades,
            SUM(CASE WHEN status = 'target' THEN 1 ELSE 0 END) AS targets,
            SUM(CASE WHEN status = 'stop_loss' THEN 1 ELSE 0 END) AS stop_losses,
            SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS eod_exits,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failures,
            ROUND(SUM(COALESCE(pnl, 0)), 2) AS total_pnl,
            ROUND(AVG(CASE WHEN pnl IS NOT NULL THEN pnl END), 2) AS avg_pnl
        FROM trades
    """
    filters, params = _trade_filter_clauses(
        strategy_name=strategy_name,
        strategy_type=strategy_type,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    if filters:
        query += " WHERE " + " AND ".join(filters)

    with _connect() as conn:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else {}


def export_trades_csv(
    path: Path | str,
    *,
    strategy_name: str | None = None,
    strategy_type: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = "id",
    sort_order: str = "desc",
) -> int:
    """Export all matching trades to CSV. Returns number of rows written."""

    rows = list_trades(
        strategy_name=strategy_name,
        strategy_type=strategy_type,
        status=status,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=None,
    )
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "id",
        "created_at",
        "updated_at",
        "strategy_name",
        "strategy_type",
        "status",
        "symbol",
        "trading_symbol",
        "option_side",
        "strike",
        "expiry",
        "direction",
        "mover_rank",
        "mover_change_pct",
        "mover_ltp",
        "spot",
        "entry_price",
        "entry_fill_price",
        "target_price",
        "stop_loss_price",
        "exit_price",
        "exit_fill_price",
        "quantity",
        "lot_size",
        "lots",
        "pnl",
        "pnl_pct",
        "exit_reason",
        "order_id",
        "order_status",
        "security_id",
        "underlying_security_id",
        "strategy_config",
        "notes",
    ]

    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return len(rows)
