"""
Aboud Trading Bot - Database v3
=================================
FIX: Stats no longer reset randomly.
     Database uses persistent storage properly.
"""
import sqlite3
import json
from datetime import datetime, timezone
from config import DATABASE_PATH, BOT_TIMEZONE


def _today_local():
    return datetime.now(BOT_TIMEZONE).strftime("%Y-%m-%d")


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair TEXT NOT NULL,
        direction TEXT NOT NULL,
        entry_time TEXT NOT NULL,
        entry_price REAL,
        exit_time TEXT,
        exit_price REAL,
        result TEXT,
        signal_sent_at TEXT,
        result_sent_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS statistics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair TEXT NOT NULL,
        total_wins INTEGER DEFAULT 0,
        total_losses INTEGER DEFAULT 0,
        daily_wins INTEGER DEFAULT 0,
        daily_losses INTEGER DEFAULT 0,
        last_reset_date TEXT,
        UNIQUE(pair)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS pending_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair TEXT NOT NULL,
        direction TEXT NOT NULL,
        detected_at TEXT NOT NULL,
        target_entry_time TEXT NOT NULL,
        indicator_data TEXT,
        status TEXT DEFAULT 'PENDING',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""")

    for k, v in {"signals_enabled": "true", "daily_report_enabled": "true"}.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    for pair in ["EURUSD", "USDJPY", "USDCHF"]:
        c.execute(
            "INSERT OR IGNORE INTO statistics (pair, total_wins, total_losses, daily_wins, daily_losses, last_reset_date) VALUES (?, 0, 0, 0, 0, ?)",
            (pair, _today_local())
        )

    conn.commit()
    conn.close()


# ============ SETTINGS ============

def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def is_signals_enabled():
    return get_setting("signals_enabled", "true") == "true"


# ============ TRADES ============

def create_trade(pair, direction, entry_time, entry_price=None):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    c.execute(
        "INSERT INTO trades (pair, direction, entry_time, entry_price, result, signal_sent_at) VALUES (?, ?, ?, ?, 'PENDING', ?)",
        (pair, direction, entry_time, entry_price, now)
    )
    tid = c.lastrowid
    conn.commit()
    conn.close()
    return tid

def update_trade_result(trade_id, exit_price, result):
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE trades SET exit_price=?, result=?, exit_time=?, result_sent_at=? WHERE id=?",
        (exit_price, result, now, now, trade_id)
    )
    conn.commit()
    conn.close()

def update_trade_entry_price(trade_id, entry_price):
    conn = get_db()
    conn.execute("UPDATE trades SET entry_price=? WHERE id=?", (entry_price, trade_id))
    conn.commit()
    conn.close()

def get_pending_trades():
    conn = get_db()
    rows = conn.execute("SELECT * FROM trades WHERE result='PENDING' ORDER BY entry_time ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_trade_by_id(tid):
    conn = get_db()
    row = conn.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_recent_trades(limit=10):
    """Get last N trades."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM trades WHERE result != 'PENDING' ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_active_trade():
    """Get current active (PENDING) trade if any."""
    conn = get_db()
    row = conn.execute("SELECT * FROM trades WHERE result='PENDING' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None

def force_close_trade(trade_id, result="LOSS"):
    """Manually close/force-close a trade."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE trades SET result=?, exit_time=?, result_sent_at=? WHERE id=? AND result='PENDING'",
        (result, now, now, trade_id)
    )
    conn.commit()
    conn.close()


# ============ STATISTICS ============
# FIX: Only reset daily stats at day boundary, never touch total stats

def _maybe_reset_daily(conn):
    """Reset daily counters if the day changed. NEVER touch totals."""
    today = _today_local()
    conn.execute(
        "UPDATE statistics SET daily_wins=0, daily_losses=0, last_reset_date=? WHERE last_reset_date != ?",
        (today, today)
    )

def update_statistics(pair, is_win):
    conn = get_db()
    _maybe_reset_daily(conn)
    if is_win:
        conn.execute("UPDATE statistics SET total_wins=total_wins+1, daily_wins=daily_wins+1 WHERE pair=?", (pair,))
    else:
        conn.execute("UPDATE statistics SET total_losses=total_losses+1, daily_losses=daily_losses+1 WHERE pair=?", (pair,))
    conn.commit()
    conn.close()

def get_statistics():
    conn = get_db()
    _maybe_reset_daily(conn)
    conn.commit()
    rows = conn.execute("SELECT * FROM statistics ORDER BY pair").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_pair_statistics(pair):
    conn = get_db()
    row = conn.execute("SELECT * FROM statistics WHERE pair=?", (pair,)).fetchone()
    conn.close()
    return dict(row) if row else None

def reset_all_statistics():
    """Reset ALL stats AND trade history."""
    conn = get_db()
    today = _today_local()
    conn.execute("UPDATE statistics SET total_wins=0, total_losses=0, daily_wins=0, daily_losses=0, last_reset_date=?", (today,))
    conn.execute("DELETE FROM trades")
    conn.execute("DELETE FROM pending_signals")
    conn.commit()
    conn.close()

def get_daily_stats():
    conn = get_db()
    _maybe_reset_daily(conn)
    conn.commit()
    rows = conn.execute("SELECT * FROM statistics ORDER BY pair").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_today_trades():
    conn = get_db()
    today = _today_local()
    rows = conn.execute("SELECT * FROM trades WHERE DATE(signal_sent_at)=? ORDER BY entry_time", (today,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============ PENDING SIGNALS ============

def create_pending_signal(pair, direction, detected_at, target_entry_time, indicator_data=None):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO pending_signals (pair, direction, detected_at, target_entry_time, indicator_data, status) VALUES (?, ?, ?, ?, ?, 'PENDING')",
        (pair, direction, detected_at, target_entry_time, json.dumps(indicator_data) if indicator_data else None)
    )
    sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid

def update_pending_signal_status(sid, status):
    conn = get_db()
    conn.execute("UPDATE pending_signals SET status=? WHERE id=?", (status, sid))
    conn.commit()
    conn.close()

def get_active_pending_signals():
    conn = get_db()
    rows = conn.execute("SELECT * FROM pending_signals WHERE status='PENDING' ORDER BY detected_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def cancel_pending_signal(sid):
    update_pending_signal_status(sid, "CANCELLED")

def confirm_pending_signal(sid):
    update_pending_signal_status(sid, "CONFIRMED")
