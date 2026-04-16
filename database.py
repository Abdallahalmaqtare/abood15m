"""
Aboud Trading Bot - Database Layer v5.3
======================================
Fixes:
- CRITICAL FIX: Full auto-migration for ALL expected columns
  (signal_time, entry_time, expiry_time, entry_price, exit_price,
   status, result, profit_loss, signal_score) in both pending_signals
   and trades tables. Solves the error:
   "column \"signal_time\" of relation \"pending_signals\" does not exist"
- Restored legacy helper functions required by main.py and admin_bot.py
- Normalized returned rows to dict objects for PostgreSQL and SQLite
- Added daily stats / today trades / signals enabled helpers
"""

import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "aboud_trading.db")
USE_POSTGRES = bool(DATABASE_URL)


def get_db_connection():
    """Return PostgreSQL or SQLite connection."""
    if USE_POSTGRES:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

    import sqlite3
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ph() -> str:
    return "%s" if USE_POSTGRES else "?"


def _dict_row(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return row


def _dict_rows(rows):
    return [_dict_row(r) for r in (rows or [])]


def _fetchone(cur):
    return _dict_row(cur.fetchone())


def _fetchall(cur):
    return _dict_rows(cur.fetchall())


def _table_info_sql(table_name: str):
    if USE_POSTGRES:
        return (
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table_name,),
        )
    return (f"PRAGMA table_info({table_name})", ())


def _get_existing_columns(conn, table_name: str):
    """Return a set of existing column names for the given table."""
    cur = conn.cursor()
    try:
        sql, params = _table_info_sql(table_name)
        cur.execute(sql, params)
        rows = cur.fetchall()
        if USE_POSTGRES:
            return {r["column_name"] if isinstance(r, dict) else r[0] for r in rows}
        return {r[1] for r in rows}
    except Exception as e:
        logger.warning("Could not list columns of %s: %s", table_name, e)
        try:
            conn.rollback()
        except Exception:
            pass
        return set()


def _ensure_column(conn, table_name: str, column_name: str, definition_sql: str):
    """Auto-add a missing column in existing deployments."""
    cur = conn.cursor()
    try:
        existing = _get_existing_columns(conn, table_name)
        if column_name not in existing:
            logger.info("🛠️  Adding missing column %s.%s", table_name, column_name)
            cur.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition_sql}"
            )
            conn.commit()
    except Exception as e:
        logger.warning("Could not ensure column %s.%s: %s", table_name, column_name, e)
        try:
            conn.rollback()
        except Exception:
            pass


def _ensure_all_columns(conn, table_name: str, columns: dict):
    """Ensure every expected column exists. columns = {name: definition_sql}."""
    for name, definition in columns.items():
        _ensure_column(conn, table_name, name, definition)


# ═══════════════════════════════════════════════
# EXPECTED COLUMNS (used by auto-migration)
# ═══════════════════════════════════════════════
_PG_NUM = "DOUBLE PRECISION"
_SL_NUM = "REAL"

def _trades_expected_columns():
    num = _PG_NUM if USE_POSTGRES else _SL_NUM
    return {
        "pair": "TEXT",
        "direction": "TEXT",
        "entry_time": "TEXT",
        "expiry_time": "TEXT",
        "entry_price": num,
        "exit_price": num,
        "status": "TEXT DEFAULT 'ACTIVE'",
        "result": "TEXT",
        "profit_loss": f"{num} DEFAULT 0",
        "signal_score": "INTEGER DEFAULT 0",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    }


def _pending_signals_expected_columns():
    return {
        "pair": "TEXT",
        "direction": "TEXT",
        "signal_time": "TEXT",
        "entry_time": "TEXT",
        "status": "TEXT DEFAULT 'PENDING'",
        "signal_score": "INTEGER DEFAULT 0",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    }


def _create_tables(cur):
    if USE_POSTGRES:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_time TEXT,
                expiry_time TEXT,
                entry_price DOUBLE PRECISION,
                exit_price DOUBLE PRECISION,
                status TEXT DEFAULT 'ACTIVE',
                result TEXT,
                profit_loss DOUBLE PRECISION DEFAULT 0,
                signal_score INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS statistics (
                id SERIAL PRIMARY KEY,
                pair TEXT NOT NULL UNIQUE,
                total_trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                draws INTEGER DEFAULT 0,
                win_rate DOUBLE PRECISION DEFAULT 0,
                current_streak INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0,
                worst_streak INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_signals (
                id SERIAL PRIMARY KEY,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                signal_time TEXT,
                entry_time TEXT,
                status TEXT DEFAULT 'PENDING',
                signal_score INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id SERIAL PRIMARY KEY,
                key TEXT NOT NULL UNIQUE,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_time TEXT,
                expiry_time TEXT,
                entry_price REAL,
                exit_price REAL,
                status TEXT DEFAULT 'ACTIVE',
                result TEXT,
                profit_loss REAL DEFAULT 0,
                signal_score INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL UNIQUE,
                total_trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                draws INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0,
                current_streak INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0,
                worst_streak INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                signal_time TEXT,
                entry_time TEXT,
                status TEXT DEFAULT 'PENDING',
                signal_score INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def init_db():
    """Create tables + migrate old DBs (idempotent)."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        _create_tables(cur)
        conn.commit()

        # ─── FULL AUTO-MIGRATION for old deployments ──────────
        # Make sure every column expected by the current code exists.
        # Handles old Render databases where new columns were never created.
        _ensure_all_columns(conn, "trades", _trades_expected_columns())
        _ensure_all_columns(conn, "pending_signals", _pending_signals_expected_columns())

        # Backfill NULL rows
        try:
            cur.execute("UPDATE trades SET signal_score = 0 WHERE signal_score IS NULL")
            cur.execute("UPDATE pending_signals SET signal_score = 0 WHERE signal_score IS NULL")
            conn.commit()
        except Exception as e:
            logger.warning("Backfill skipped: %s", e)
            conn.rollback()

        # Initial statistics rows
        from config import TRADING_PAIRS
        for pair in TRADING_PAIRS:
            if USE_POSTGRES:
                cur.execute(
                    "INSERT INTO statistics (pair) VALUES (%s) ON CONFLICT (pair) DO NOTHING",
                    (pair,),
                )
            else:
                cur.execute("INSERT OR IGNORE INTO statistics (pair) VALUES (?)", (pair,))
        conn.commit()

        # Default settings
        if get_setting("signals_enabled", None) is None:
            set_setting("signals_enabled", "true")

        logger.info("✅ Database initialized & migrated successfully")
    except Exception as e:
        logger.error("❌ Database initialization failed: %s", e, exc_info=True)
        conn.rollback()
        raise
    finally:
        conn.close()


# ═══════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════

def get_setting(key, default=None):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT value FROM settings WHERE key = {_ph()}", (key,))
        row = _fetchone(cur)
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key, value):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if USE_POSTGRES:
            cur.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, str(value)),
            )
        else:
            cur.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (key, str(value)),
            )
        conn.commit()
    finally:
        conn.close()


def is_signals_enabled():
    return str(get_setting("signals_enabled", "true")).lower() == "true"


# ═══════════════════════════════════════════════
# PENDING SIGNALS
# ═══════════════════════════════════════════════

def create_pending_signal(pair, direction, signal_time, entry_time, status="PENDING", signal_score=0):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if USE_POSTGRES:
            cur.execute(
                """
                INSERT INTO pending_signals (pair, direction, signal_time, entry_time, status, signal_score)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (pair, direction, signal_time, entry_time, status, signal_score),
            )
            row = _fetchone(cur)
            signal_id = row["id"] if row else None
        else:
            cur.execute(
                """
                INSERT INTO pending_signals (pair, direction, signal_time, entry_time, status, signal_score)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pair, direction, signal_time, entry_time, status, signal_score),
            )
            signal_id = cur.lastrowid
        conn.commit()
        return signal_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_pending_signal(signal_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM pending_signals WHERE id = {_ph()}", (signal_id,))
        return _fetchone(cur)
    finally:
        conn.close()


def update_pending_signal(signal_id, status):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            f"UPDATE pending_signals SET status = {_ph()} WHERE id = {_ph()}",
            (status, signal_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_pending_signal(signal_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"DELETE FROM pending_signals WHERE id = {_ph()}", (signal_id,))
        conn.commit()
    finally:
        conn.close()


def get_active_pending_signals():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT * FROM pending_signals
            WHERE status IN ('PENDING', 'ACCEPTED', 'ACTIVE')
            ORDER BY created_at DESC
            """
        )
        return _fetchall(cur)
    finally:
        conn.close()


def get_pending_trades():
    return get_active_pending_signals()


# ═══════════════════════════════════════════════
# TRADES
# ═══════════════════════════════════════════════

def create_trade(pair, direction, entry_time, expiry_time, status="ACTIVE", signal_score=0):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if USE_POSTGRES:
            cur.execute(
                """
                INSERT INTO trades (pair, direction, entry_time, expiry_time, status, signal_score)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (pair, direction, entry_time, expiry_time, status, signal_score),
            )
            row = _fetchone(cur)
            trade_id = row["id"] if row else None
        else:
            cur.execute(
                """
                INSERT INTO trades (pair, direction, entry_time, expiry_time, status, signal_score)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pair, direction, entry_time, expiry_time, status, signal_score),
            )
            trade_id = cur.lastrowid
        conn.commit()
        return trade_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_trade(trade_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM trades WHERE id = {_ph()}", (trade_id,))
        return _fetchone(cur)
    finally:
        conn.close()


def update_trade(trade_id, **kwargs):
    if not kwargs:
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        sets = []
        values = []
        for key, value in kwargs.items():
            sets.append(f"{key} = {_ph()}")
            values.append(value)
        values.append(trade_id)
        cur.execute(f"UPDATE trades SET {', '.join(sets)} WHERE id = {_ph()}", tuple(values))
        conn.commit()
    finally:
        conn.close()


def get_active_trades():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM trades WHERE status = 'ACTIVE' ORDER BY created_at DESC")
        return _fetchall(cur)
    finally:
        conn.close()


def get_active_trade():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM trades WHERE status = 'ACTIVE' ORDER BY created_at DESC LIMIT 1")
        return _fetchone(cur)
    finally:
        conn.close()


def get_recent_trades(limit=10):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT * FROM trades WHERE status != 'ACTIVE' ORDER BY created_at DESC LIMIT {_ph()}",
            (limit,),
        )
        return _fetchall(cur)
    finally:
        conn.close()


def get_today_trades():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if USE_POSTGRES:
            cur.execute(
                """
                SELECT * FROM trades
                WHERE DATE(created_at AT TIME ZONE 'UTC') = CURRENT_DATE
                ORDER BY created_at DESC
                """
            )
        else:
            cur.execute(
                "SELECT * FROM trades WHERE DATE(created_at) = DATE('now') ORDER BY created_at DESC"
            )
        return _fetchall(cur)
    finally:
        conn.close()


def force_close_trade(trade_id, result="LOSS"):
    trade = get_trade(trade_id)
    if not trade:
        return False
    update_trade(trade_id, status="COMPLETED", result=result)
    update_statistics(trade["pair"], result)
    return True


# ═══════════════════════════════════════════════
# STATISTICS
# ═══════════════════════════════════════════════

def _normalize_stats_row(row):
    if not row:
        return None
    return {
        **row,
        "total_wins": row.get("wins", 0),
        "total_losses": row.get("losses", 0),
        "total_draws": row.get("draws", 0),
    }


def update_statistics(pair, result):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM statistics WHERE pair = {_ph()}", (pair,))
        stats = _fetchone(cur)
        if not stats:
            if USE_POSTGRES:
                cur.execute("INSERT INTO statistics (pair) VALUES (%s) ON CONFLICT (pair) DO NOTHING", (pair,))
            else:
                cur.execute("INSERT OR IGNORE INTO statistics (pair) VALUES (?)", (pair,))
            conn.commit()
            cur.execute(f"SELECT * FROM statistics WHERE pair = {_ph()}", (pair,))
            stats = _fetchone(cur)

        total = int(stats.get("total_trades", 0)) + 1
        wins = int(stats.get("wins", 0))
        losses = int(stats.get("losses", 0))
        draws = int(stats.get("draws", 0))
        streak = int(stats.get("current_streak", 0))
        best = int(stats.get("best_streak", 0))
        worst = int(stats.get("worst_streak", 0))

        if result == "WIN":
            wins += 1
            streak = streak + 1 if streak > 0 else 1
            best = max(best, streak)
        elif result == "LOSS":
            losses += 1
            streak = streak - 1 if streak < 0 else -1
            worst = min(worst, streak)
        else:
            draws += 1
            streak = 0

        win_rate = round((wins / total) * 100, 2) if total else 0

        cur.execute(
            f"""
            UPDATE statistics
            SET total_trades = {_ph()}, wins = {_ph()}, losses = {_ph()}, draws = {_ph()},
                win_rate = {_ph()}, current_streak = {_ph()}, best_streak = {_ph()},
                worst_streak = {_ph()}, updated_at = CURRENT_TIMESTAMP
            WHERE pair = {_ph()}
            """,
            (total, wins, losses, draws, win_rate, streak, best, worst, pair),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_statistics(pair=None):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if pair:
            cur.execute(f"SELECT * FROM statistics WHERE pair = {_ph()}", (pair,))
            return _normalize_stats_row(_fetchone(cur))
        cur.execute("SELECT * FROM statistics ORDER BY pair")
        return [_normalize_stats_row(x) for x in _fetchall(cur)]
    finally:
        conn.close()


def get_overall_statistics():
    return get_statistics()


def get_daily_stats():
    from config import TRADING_PAIRS

    overall_map = {row["pair"]: row for row in (get_statistics() or [])}
    today_trades = get_today_trades()

    result = []
    for pair in TRADING_PAIRS:
        totals = overall_map.get(pair, {})
        pair_today = [t for t in today_trades if t.get("pair") == pair]
        daily_wins = sum(1 for t in pair_today if t.get("result") == "WIN")
        daily_losses = sum(1 for t in pair_today if t.get("result") == "LOSS")
        daily_draws = sum(1 for t in pair_today if t.get("result") == "DRAW")
        result.append(
            {
                "pair": pair,
                "daily_wins": daily_wins,
                "daily_losses": daily_losses,
                "daily_draws": daily_draws,
                "total_wins": int(totals.get("total_wins", 0)),
                "total_losses": int(totals.get("total_losses", 0)),
                "total_draws": int(totals.get("total_draws", 0)),
                "total_trades": int(totals.get("total_trades", 0)),
                "win_rate": float(totals.get("win_rate", 0)),
            }
        )
    return result


# ═══════════════════════════════════════════════
# MAINTENANCE
# ═══════════════════════════════════════════════

def reset_all_statistics():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE statistics
            SET total_trades = 0, wins = 0, losses = 0, draws = 0,
                win_rate = 0, current_streak = 0, best_streak = 0,
                worst_streak = 0, updated_at = CURRENT_TIMESTAMP
            """
        )
        cur.execute("DELETE FROM trades")
        cur.execute("DELETE FROM pending_signals")
        conn.commit()
    finally:
        conn.close()
