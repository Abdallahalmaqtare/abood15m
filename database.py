"""
Aboud Trading Bot - Database Module v2
=====================================
Added: has_active_trade(), find_duplicate_trade()
"""

import sqlite3
import json
from datetime import datetime, timezone
from config import DATABASE_PATH


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
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
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            total_wins INTEGER DEFAULT 0,
            total_losses INTEGER DEFAULT 0,
            daily_wins INTEGER DEFAULT 0,
            daily_losses INTEGER DEFAULT 0,
            last_reset_date TEXT,
            UNIQUE(pair)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            target_entry_time TEXT NOT NULL,
            indicator_data TEXT,
            status TEXT DEFAULT 'PENDING',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    defaults = {
        "signals_enabled": "true",
        "daily_report_enabled": "true",
    }
    for key, value in defaults.items():
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )

    for pair in ["EURUSD", "USDJPY", "USDCHF"]:
        cursor.execute(
            "INSERT OR IGNORE INTO statistics (pair, total_wins, total_losses, daily_wins, daily_losses, last_reset_date) VALUES (?, 0, 0, 0, 0, ?)",
            (pair, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        )

    conn.commit()
    conn.close()


# ============================================
# SETTINGS
# ============================================

def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value))
    )
    conn.commit()
    conn.close()


def is_signals_enabled():
    return get_setting("signals_enabled", "true") == "true"


# ============================================
# TRADE OPERATIONS
# ============================================

def create_trade(pair, direction, entry_time, entry_price=None):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        """INSERT INTO trades (pair, direction, entry_time, entry_price, result, signal_sent_at)
           VALUES (?, ?, ?, ?, 'PENDING', ?)""",
        (pair, direction, entry_time, entry_price, now)
    )
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def update_trade_result(trade_id, exit_price, result):
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE trades SET exit_price = ?, result = ?, exit_time = ?, result_sent_at = ?
           WHERE id = ?""",
        (exit_price, result, now, now, trade_id)
    )
    conn.commit()
    conn.close()


def update_trade_entry_price(trade_id, entry_price):
    conn = get_db()
    conn.execute(
        "UPDATE trades SET entry_price = ? WHERE id = ?",
        (entry_price, trade_id)
    )
    conn.commit()
    conn.close()


def get_pending_trades():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM trades WHERE result = 'PENDING' ORDER BY entry_time ASC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_trade_by_id(trade_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ============================================
# NEW: ACTIVE TRADE CHECK (prevents overlapping)
# ============================================

def has_active_trade():
    """Check if there is any trade still PENDING (not yet resolved)."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM trades WHERE result = 'PENDING'"
    ).fetchone()
    conn.close()
    return row["cnt"] > 0


def find_duplicate_trade(pair, entry_time):
    """Check if a trade already exists for this pair and entry time."""
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM trades WHERE pair = ? AND entry_time = ? AND result = 'PENDING'",
        (pair, entry_time)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ============================================
# STATISTICS
# ============================================

def update_statistics(pair, is_win):
    conn = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    row = conn.execute(
        "SELECT last_reset_date FROM statistics WHERE pair = ?", (pair,)
    ).fetchone()

    if row and row["last_reset_date"] != today:
        conn.execute(
            "UPDATE statistics SET daily_wins = 0, daily_losses = 0, last_reset_date = ? WHERE pair = ?",
            (today, pair)
        )

    if is_win:
        conn.execute(
            "UPDATE statistics SET total_wins = total_wins + 1, daily_wins = daily_wins + 1 WHERE pair = ?",
            (pair,)
        )
    else:
        conn.execute(
            "UPDATE statistics SET total_losses = total_losses + 1, daily_losses = daily_losses + 1 WHERE pair = ?",
            (pair,)
        )

    conn.commit()
    conn.close()


def get_statistics():
    conn = get_db()
    rows = conn.execute("SELECT * FROM statistics ORDER BY pair").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_pair_statistics(pair):
    conn = get_db()
    row = conn.execute("SELECT * FROM statistics WHERE pair = ?", (pair,)).fetchone()
    conn.close()
    return dict(row) if row else None


def reset_all_statistics():
    conn = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """UPDATE statistics SET total_wins = 0, total_losses = 0,
           daily_wins = 0, daily_losses = 0, last_reset_date = ?""",
        (today,)
    )
    # Also delete all trade history
    conn.execute("DELETE FROM trades")
    conn.execute("DELETE FROM pending_signals")
    conn.commit()
    conn.close()


def get_daily_stats():
    conn = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """UPDATE statistics SET daily_wins = 0, daily_losses = 0, last_reset_date = ?
           WHERE last_reset_date != ?""",
        (today, today)
    )
    conn.commit()
    rows = conn.execute("SELECT * FROM statistics ORDER BY pair").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_today_trades():
    conn = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT * FROM trades WHERE DATE(signal_sent_at) = ? ORDER BY entry_time",
        (today,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ============================================
# PENDING SIGNALS
# ============================================

def create_pending_signal(pair, direction, detected_at, target_entry_time, indicator_data=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO pending_signals (pair, direction, detected_at, target_entry_time, indicator_data, status)
           VALUES (?, ?, ?, ?, ?, 'PENDING')""",
        (pair, direction, detected_at, target_entry_time, json.dumps(indicator_data) if indicator_data else None)
    )
    signal_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return signal_id


def update_pending_signal_status(signal_id, status):
    conn = get_db()
    conn.execute(
        "UPDATE pending_signals SET status = ? WHERE id = ?",
        (status, signal_id)
    )
    conn.commit()
    conn.close()


def get_active_pending_signals():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM pending_signals WHERE status = 'PENDING' ORDER BY detected_at"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def cancel_pending_signal(signal_id):
    update_pending_signal_status(signal_id, "CANCELLED")


def confirm_pending_signal(signal_id):
    update_pending_signal_status(signal_id, "CONFIRMED")
