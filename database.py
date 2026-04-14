"""
Aboud Trading Bot - Database v5 (UPGRADED)
=============================================
Updated for EURUSD + GBPUSD only.
Uses Neon PostgreSQL = DATA NEVER LOST.
Falls back to SQLite only for local testing.
"""
import json
import logging
from datetime import datetime, timezone
from config import DATABASE_URL, BOT_TIMEZONE

logger = logging.getLogger(__name__)

# ============================================
# AUTO-DETECT: PostgreSQL or SQLite
# ============================================
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    logger.info("Using PostgreSQL (Neon) - PERMANENT storage")
else:
    import sqlite3
    logger.info("Using SQLite - LOCAL only (data lost on restart)")

_PH = "%s" if USE_POSTGRES else "?"  # placeholder


def _today_local():
    return datetime.now(BOT_TIMEZONE).strftime("%Y-%m-%d")


def get_db():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect("aboud_trading.db")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def _fetchall(cursor):
    """Convert rows to list of dicts for both PG and SQLite."""
    if USE_POSTGRES:
        cols = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    else:
        return [dict(row) for row in cursor.fetchall()]


def _fetchone(cursor):
    if USE_POSTGRES:
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))
    else:
        row = cursor.fetchone()
        return dict(row) if row else None


def init_db():
    conn = get_db()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            entry_price REAL,
            exit_time TEXT,
            exit_price REAL,
            result TEXT,
            signal_score REAL,
            signal_sent_at TEXT,
            result_sent_at TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS statistics (
            id SERIAL PRIMARY KEY,
            pair TEXT NOT NULL UNIQUE,
            total_wins INTEGER DEFAULT 0,
            total_losses INTEGER DEFAULT 0,
            daily_wins INTEGER DEFAULT 0,
            daily_losses INTEGER DEFAULT 0,
            last_reset_date TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS pending_signals (
            id SERIAL PRIMARY KEY,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            target_entry_time TEXT NOT NULL,
            indicator_data TEXT,
            signal_score REAL,
            status TEXT DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT NOW()
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
    else:
        c.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL, direction TEXT NOT NULL,
            entry_time TEXT NOT NULL, entry_price REAL,
            exit_time TEXT, exit_price REAL, result TEXT,
            signal_score REAL,
            signal_sent_at TEXT, result_sent_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL UNIQUE,
            total_wins INTEGER DEFAULT 0, total_losses INTEGER DEFAULT 0,
            daily_wins INTEGER DEFAULT 0, daily_losses INTEGER DEFAULT 0,
            last_reset_date TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS pending_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL, direction TEXT NOT NULL,
            detected_at TEXT NOT NULL, target_entry_time TEXT NOT NULL,
            indicator_data TEXT, signal_score REAL,
            status TEXT DEFAULT 'PENDING',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        )""")

    # Default settings
    for k, v in {"signals_enabled": "true", "daily_report_enabled": "true", "last_startup": ""}.items():
        if USE_POSTGRES:
            c.execute(f"INSERT INTO settings (key, value) VALUES ({_PH}, {_PH}) ON CONFLICT (key) DO NOTHING", (k, v))
        else:
            c.execute(f"INSERT OR IGNORE INTO settings (key, value) VALUES ({_PH}, {_PH})", (k, v))

    # Init stats per pair - UPDATED: EURUSD + GBPUSD only
    for pair in ["EURUSD", "GBPUSD"]:
        if USE_POSTGRES:
            c.execute(f"""INSERT INTO statistics (pair, total_wins, total_losses, daily_wins, daily_losses, last_reset_date)
                         VALUES ({_PH}, 0, 0, 0, 0, {_PH}) ON CONFLICT (pair) DO NOTHING""", (pair, _today_local()))
        else:
            c.execute(f"""INSERT OR IGNORE INTO statistics (pair, total_wins, total_losses, daily_wins, daily_losses, last_reset_date)
                         VALUES ({_PH}, 0, 0, 0, 0, {_PH})""", (pair, _today_local()))

    conn.commit()
    conn.close()
    logger.info(f"DB initialized ({'PostgreSQL' if USE_POSTGRES else 'SQLite'})")


# ============ SETTINGS ============

def get_setting(key, default=None):
    conn = get_db()
    c = conn.cursor()
    c.execute(f"SELECT value FROM settings WHERE key = {_PH}", (key,))
    row = _fetchone(c)
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_db()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute(f"INSERT INTO settings (key, value) VALUES ({_PH}, {_PH}) ON CONFLICT (key) DO UPDATE SET value = {_PH}", (key, str(value), str(value)))
    else:
        c.execute(f"INSERT OR REPLACE INTO settings (key, value) VALUES ({_PH}, {_PH})", (key, str(value)))
    conn.commit()
    conn.close()


def is_signals_enabled():
    return get_setting("signals_enabled", "true") == "true"


# ============ TRADES ============

def create_trade(pair, direction, entry_time, entry_price=None, signal_score=None):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    if USE_POSTGRES:
        c.execute(
            f"INSERT INTO trades (pair, direction, entry_time, entry_price, result, signal_score, signal_sent_at) VALUES ({_PH},{_PH},{_PH},{_PH},'PENDING',{_PH},{_PH}) RETURNING id",
            (pair, direction, entry_time, entry_price, signal_score, now))
        tid = c.fetchone()[0]
    else:
        c.execute(
            f"INSERT INTO trades (pair, direction, entry_time, entry_price, result, signal_score, signal_sent_at) VALUES ({_PH},{_PH},{_PH},{_PH},'PENDING',{_PH},{_PH})",
            (pair, direction, entry_time, entry_price, signal_score, now))
        tid = c.lastrowid
    conn.commit()
    conn.close()
    return tid


def update_trade_result(trade_id, exit_price, result):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    c.execute(f"UPDATE trades SET exit_price={_PH}, result={_PH}, exit_time={_PH}, result_sent_at={_PH} WHERE id={_PH}",
              (exit_price, result, now, now, trade_id))
    conn.commit()
    conn.close()


def update_trade_entry_price(trade_id, entry_price):
    conn = get_db()
    c = conn.cursor()
    c.execute(f"UPDATE trades SET entry_price={_PH} WHERE id={_PH}", (entry_price, trade_id))
    conn.commit()
    conn.close()


def get_pending_trades():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE result='PENDING' ORDER BY entry_time ASC")
    rows = _fetchall(c)
    conn.close()
    return rows


def get_trade_by_id(tid):
    conn = get_db()
    c = conn.cursor()
    c.execute(f"SELECT * FROM trades WHERE id={_PH}", (tid,))
    row = _fetchone(c)
    conn.close()
    return row


def get_recent_trades(limit=10):
    conn = get_db()
    c = conn.cursor()
    c.execute(f"SELECT * FROM trades WHERE result != 'PENDING' ORDER BY id DESC LIMIT {_PH}", (limit,))
    rows = _fetchall(c)
    conn.close()
    return rows


def get_active_trade():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE result='PENDING' ORDER BY id DESC LIMIT 1")
    row = _fetchone(c)
    conn.close()
    return row


def force_close_trade(trade_id, result="LOSS"):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    c.execute(f"UPDATE trades SET result={_PH}, exit_time={_PH}, result_sent_at={_PH} WHERE id={_PH} AND result='PENDING'",
              (result, now, now, trade_id))
    conn.commit()
    conn.close()


# ============ STATISTICS ============

def _maybe_reset_daily(conn):
    today = _today_local()
    c = conn.cursor()
    c.execute(f"UPDATE statistics SET daily_wins=0, daily_losses=0, last_reset_date={_PH} WHERE last_reset_date != {_PH}",
              (today, today))


def update_statistics(pair, is_win):
    conn = get_db()
    _maybe_reset_daily(conn)
    c = conn.cursor()
    if is_win:
        c.execute(f"UPDATE statistics SET total_wins=total_wins+1, daily_wins=daily_wins+1 WHERE pair={_PH}", (pair,))
    else:
        c.execute(f"UPDATE statistics SET total_losses=total_losses+1, daily_losses=daily_losses+1 WHERE pair={_PH}", (pair,))
    conn.commit()
    conn.close()


def get_statistics():
    conn = get_db()
    _maybe_reset_daily(conn)
    conn.commit()
    c = conn.cursor()
    c.execute("SELECT * FROM statistics ORDER BY pair")
    rows = _fetchall(c)
    conn.close()
    return rows


def get_pair_statistics(pair):
    conn = get_db()
    c = conn.cursor()
    c.execute(f"SELECT * FROM statistics WHERE pair={_PH}", (pair,))
    row = _fetchone(c)
    conn.close()
    return row


def reset_all_statistics():
    conn = get_db()
    c = conn.cursor()
    today = _today_local()
    c.execute(f"UPDATE statistics SET total_wins=0, total_losses=0, daily_wins=0, daily_losses=0, last_reset_date={_PH}", (today,))
    c.execute("DELETE FROM trades")
    c.execute("DELETE FROM pending_signals")
    conn.commit()
    conn.close()


def get_daily_stats():
    conn = get_db()
    _maybe_reset_daily(conn)
    conn.commit()
    c = conn.cursor()
    c.execute("SELECT * FROM statistics ORDER BY pair")
    rows = _fetchall(c)
    conn.close()
    return rows


def get_today_trades():
    conn = get_db()
    c = conn.cursor()
    today = _today_local()
    c.execute(f"SELECT * FROM trades WHERE signal_sent_at LIKE {_PH} ORDER BY entry_time", (today + '%',))
    rows = _fetchall(c)
    conn.close()
    return rows


# ============ PENDING SIGNALS ============

def create_pending_signal(pair, direction, detected_at, target_entry_time, indicator_data=None, signal_score=None):
    conn = get_db()
    c = conn.cursor()
    ind = json.dumps(indicator_data) if indicator_data else None
    if USE_POSTGRES:
        c.execute(f"INSERT INTO pending_signals (pair, direction, detected_at, target_entry_time, indicator_data, signal_score, status) VALUES ({_PH},{_PH},{_PH},{_PH},{_PH},{_PH},'PENDING') RETURNING id",
                  (pair, direction, detected_at, target_entry_time, ind, signal_score))
        sid = c.fetchone()[0]
    else:
        c.execute(f"INSERT INTO pending_signals (pair, direction, detected_at, target_entry_time, indicator_data, signal_score, status) VALUES ({_PH},{_PH},{_PH},{_PH},{_PH},{_PH},'PENDING')",
                  (pair, direction, detected_at, target_entry_time, ind, signal_score))
        sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid


def update_pending_signal_status(sid, status):
    conn = get_db()
    c = conn.cursor()
    c.execute(f"UPDATE pending_signals SET status={_PH} WHERE id={_PH}", (status, sid))
    conn.commit()
    conn.close()


def get_active_pending_signals():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM pending_signals WHERE status='PENDING' ORDER BY detected_at")
    rows = _fetchall(c)
    conn.close()
    return rows


def cancel_pending_signal(sid):
    update_pending_signal_status(sid, "CANCELLED")

def confirm_pending_signal(sid):
    update_pending_signal_status(sid, "CONFIRMED")
