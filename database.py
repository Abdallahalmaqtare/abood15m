"""
Aboud Trading Bot - Database Module
=====================================
SQLite database for storing trades, statistics, and settings.
"""

import sqlite3
import json
from datetime import datetime, timezone
from config import DATABASE_PATH


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Initialize database tables."""
    conn = get_db()
    cursor = conn.cursor()

    # Trades table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,  -- CALL or PUT
            entry_time TEXT NOT NULL,
            entry_price REAL,
            exit_time TEXT,
            exit_price REAL,
            result TEXT,  -- WIN, LOSS, PENDING
            signal_sent_at TEXT,
            result_sent_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Statistics table (running totals per pair)
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

    # Pending signals (temporary signals waiting for confirmation)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            target_entry_time TEXT NOT NULL,
            indicator_data TEXT,  -- JSON with indicator values
            status TEXT DEFAULT 'PENDING',  -- PENDING, CONFIRMED, CANCELLED
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Bot settings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Initialize default settings
    defaults = {
        "signals_enabled": "true",
        "daily_report_enabled": "true",
    }
    for key, value in defaults.items():
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )

    # Initialize statistics for each pair
    for pair in ["EURUSD", "USDJPY", "USDCHF"]:
        cursor.execute(
            "INSERT OR IGNORE INTO statistics (pair, total_wins, total_losses, daily_wins, daily_losses, last_reset_date) VALUES (?, 0, 0, 0, 0, ?)",
            (pair, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        )

    conn.commit()
    conn.close()


# ============================================
# SETTINGS OPERATIONS
# ============================================

def get_setting(key, default=None):
    """Get a setting value."""
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    """Set a setting value."""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value))
    )
    conn.commit()
    conn.close()


def is_signals_enabled():
    """Check if signals are enabled."""
    return get_setting("signals_enabled", "true") == "true"


# ============================================
# TRADE OPERATIONS
# ============================================

def create_trade(pair, direction, entry_time, entry_price=None):
    """Create a new trade record."""
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
    """Update trade result after expiry."""
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
    """Update the entry price for a trade."""
    conn = get_db()
    conn.execute(
        "UPDATE trades SET entry_price = ? WHERE id = ?",
        (entry_price, trade_id)
    )
    conn.commit()
    conn.close()


def get_pending_trades():
    """Get all trades with PENDING result."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM trades WHERE result = 'PENDING' ORDER BY entry_time ASC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_trade_by_id(trade_id):
    """Get a specific trade."""
    conn = get_db()
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ============================================
# STATISTICS OPERATIONS
# ============================================

def update_statistics(pair, is_win):
    """Update statistics after a trade result."""
    conn = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check if we need to reset daily stats
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
    """Get all statistics."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM statistics ORDER BY pair").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_pair_statistics(pair):
    """Get statistics for a specific pair."""
    conn = get_db()
    row = conn.execute("SELECT * FROM statistics WHERE pair = ?", (pair,)).fetchone()
    conn.close()
    return dict(row) if row else None


def reset_all_statistics():
    """Reset all statistics to zero."""
    conn = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """UPDATE statistics SET total_wins = 0, total_losses = 0,
           daily_wins = 0, daily_losses = 0, last_reset_date = ?""",
        (today,)
    )
    conn.commit()
    conn.close()


def get_daily_stats():
    """Get today's statistics."""
    conn = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Reset daily if needed
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
    """Get all trades from today."""
    conn = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT * FROM trades WHERE DATE(signal_sent_at) = ? ORDER BY entry_time",
        (today,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ============================================
# PENDING SIGNALS OPERATIONS
# ============================================

def create_pending_signal(pair, direction, detected_at, target_entry_time, indicator_data=None):
    """Create a pending (temporary) signal."""
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
    """Update pending signal status."""
    conn = get_db()
    conn.execute(
        "UPDATE pending_signals SET status = ? WHERE id = ?",
        (status, signal_id)
    )
    conn.commit()
    conn.close()


def get_active_pending_signals():
    """Get all active pending signals."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM pending_signals WHERE status = 'PENDING' ORDER BY detected_at"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def cancel_pending_signal(signal_id):
    """Cancel a pending signal."""
    update_pending_signal_status(signal_id, "CANCELLED")


def confirm_pending_signal(signal_id):
    """Confirm a pending signal."""
    update_pending_signal_status(signal_id, "CONFIRMED")
