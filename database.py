"""
Database module - Aboud Trading Bot v5.0 PRO
PostgreSQL / SQLite with auto-migration support
"""

import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_db_connection():
    """Get database connection - PostgreSQL if DATABASE_URL set, else SQLite."""
    if DATABASE_URL:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect("bot_database.db")
        conn.row_factory = sqlite3.Row
        return conn


def _get_placeholder():
    """Return %s for PostgreSQL, ? for SQLite."""
    return "%s" if DATABASE_URL else "?"


def _ensure_column(conn, table_name: str, column_name: str, col_type: str = "INTEGER DEFAULT 0"):
    """
    Auto-migration: add a column if it doesn't exist yet.
    Works with both PostgreSQL and SQLite.
    """
    cur = conn.cursor()
    try:
        if DATABASE_URL:
            # PostgreSQL
            cur.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
                (table_name, column_name),
            )
            exists = cur.fetchone() is not None
        else:
            # SQLite
            cur.execute(f"PRAGMA table_info({table_name})")
            exists = any(row[1] == column_name for row in cur.fetchall())

        if not exists:
            logger.info("🔧 Auto-migration: adding column %s.%s", table_name, column_name)
            cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {col_type}")
            conn.commit()
            logger.info("✅ Column %s.%s added successfully", table_name, column_name)
    except Exception as e:
        logger.error("❌ Failed to add column %s.%s: %s", table_name, column_name, e)
        try:
            conn.rollback()
        except Exception:
            pass


def init_db():
    """Initialize database tables and run migrations."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()

    try:
        # ── trades table ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
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
        """)

        # ── statistics table ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS statistics (
                id SERIAL PRIMARY KEY,
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
        """)

        # ── pending_signals table ──
        cur.execute("""
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
        """)

        # ── settings table ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id SERIAL PRIMARY KEY,
                key TEXT NOT NULL UNIQUE,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()

        # ── Auto-migration for existing databases ──
        _ensure_column(conn, "trades", "signal_score", "INTEGER DEFAULT 0")
        _ensure_column(conn, "pending_signals", "signal_score", "INTEGER DEFAULT 0")

        # Backfill NULLs
        try:
            cur.execute("UPDATE trades SET signal_score = 0 WHERE signal_score IS NULL")
            cur.execute("UPDATE pending_signals SET signal_score = 0 WHERE signal_score IS NULL")
            conn.commit()
        except Exception as e:
            logger.warning("Backfill signal_score skipped: %s", e)

        # ── Initialize statistics rows for each trading pair ──
        from config import TRADING_PAIRS
        for pair in TRADING_PAIRS:
            try:
                if DATABASE_URL:
                    cur.execute(
                        "INSERT INTO statistics (pair) VALUES (%s) ON CONFLICT (pair) DO NOTHING",
                        (pair,),
                    )
                else:
                    cur.execute(
                        "INSERT OR IGNORE INTO statistics (pair) VALUES (?)",
                        (pair,),
                    )
            except Exception as e:
                logger.warning("Stats init for %s skipped: %s", pair, e)

        conn.commit()
        logger.info("✅ Database initialized successfully")

    except Exception as e:
        logger.error("❌ Database initialization failed: %s", e)
        raise
    finally:
        conn.close()


# ═══════════════════════════════════════════════
#  PENDING SIGNALS
# ═══════════════════════════════════════════════

def create_pending_signal(pair, direction, signal_time, entry_time, status='PENDING', signal_score=0):
    """Create a new pending signal record."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        cur.execute(
            f"""
            INSERT INTO pending_signals (pair, direction, signal_time, entry_time, status, signal_score)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            RETURNING id
            """,
            (pair, direction, signal_time, entry_time, status, signal_score),
        )
        row = cur.fetchone()
        conn.commit()
        signal_id = row[0] if row else None
        logger.info("📝 Pending signal created: id=%s pair=%s dir=%s score=%s", signal_id, pair, direction, signal_score)
        return signal_id
    except Exception as e:
        logger.error("❌ create_pending_signal failed: %s", e)
        conn.rollback()
        raise
    finally:
        conn.close()


def get_pending_signal(signal_id):
    """Get a pending signal by ID."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        cur.execute(f"SELECT * FROM pending_signals WHERE id = {ph}", (signal_id,))
        return cur.fetchone()
    finally:
        conn.close()


def update_pending_signal(signal_id, status):
    """Update pending signal status."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        cur.execute(
            f"UPDATE pending_signals SET status = {ph} WHERE id = {ph}",
            (status, signal_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_pending_signal(signal_id):
    """Delete a pending signal."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        cur.execute(f"DELETE FROM pending_signals WHERE id = {ph}", (signal_id,))
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════
#  TRADES
# ═══════════════════════════════════════════════

def create_trade(pair, direction, entry_time, expiry_time, status='ACTIVE', signal_score=0):
    """Create a new trade record."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        cur.execute(
            f"""
            INSERT INTO trades (pair, direction, entry_time, expiry_time, status, signal_score)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            RETURNING id
            """,
            (pair, direction, entry_time, expiry_time, status, signal_score),
        )
        row = cur.fetchone()
        conn.commit()
        trade_id = row[0] if row else None
        logger.info("📊 Trade created: id=%s pair=%s dir=%s score=%s", trade_id, pair, direction, signal_score)
        return trade_id
    except Exception as e:
        logger.error("❌ create_trade failed: %s", e)
        conn.rollback()
        raise
    finally:
        conn.close()


def get_trade(trade_id):
    """Get a trade by ID."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        cur.execute(f"SELECT * FROM trades WHERE id = {ph}", (trade_id,))
        return cur.fetchone()
    finally:
        conn.close()


def update_trade(trade_id, **kwargs):
    """Update trade fields dynamically."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        set_clauses = []
        values = []
        for key, value in kwargs.items():
            set_clauses.append(f"{key} = {ph}")
            values.append(value)
        values.append(trade_id)
        query = f"UPDATE trades SET {', '.join(set_clauses)} WHERE id = {ph}"
        cur.execute(query, tuple(values))
        conn.commit()
    finally:
        conn.close()


def get_active_trades():
    """Get all active trades."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM trades WHERE status = 'ACTIVE' ORDER BY created_at DESC")
        return cur.fetchall()
    finally:
        conn.close()


def get_recent_trades(limit=10):
    """Get recent completed trades."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        cur.execute(
            f"SELECT * FROM trades WHERE status != 'ACTIVE' ORDER BY created_at DESC LIMIT {ph}",
            (limit,),
        )
        return cur.fetchall()
    finally:
        conn.close()


# ═══════════════════════════════════════════════
#  STATISTICS
# ═══════════════════════════════════════════════

def update_statistics(pair, result):
    """Update win/loss statistics for a pair."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        cur.execute(f"SELECT * FROM statistics WHERE pair = {ph}", (pair,))
        stats = cur.fetchone()

        if not stats:
            logger.warning("No statistics row for %s, creating...", pair)
            if DATABASE_URL:
                cur.execute("INSERT INTO statistics (pair) VALUES (%s) ON CONFLICT (pair) DO NOTHING", (pair,))
            else:
                cur.execute("INSERT OR IGNORE INTO statistics (pair) VALUES (?)", (pair,))
            conn.commit()
            cur.execute(f"SELECT * FROM statistics WHERE pair = {ph}", (pair,))
            stats = cur.fetchone()

        if DATABASE_URL:
            total = stats[2] + 1  # total_trades
            wins = stats[3]       # wins
            losses = stats[4]     # losses
            draws = stats[5]      # draws
            streak = stats[7]     # current_streak
            best = stats[8]       # best_streak
            worst = stats[9]      # worst_streak
        else:
            total = stats['total_trades'] + 1
            wins = stats['wins']
            losses = stats['losses']
            draws = stats['draws']
            streak = stats['current_streak']
            best = stats['best_streak']
            worst = stats['worst_streak']

        if result == 'WIN':
            wins += 1
            streak = streak + 1 if streak > 0 else 1
            best = max(best, streak)
        elif result == 'LOSS':
            losses += 1
            streak = streak - 1 if streak < 0 else -1
            worst = min(worst, streak)
        else:
            draws += 1
            streak = 0

        win_rate = (wins / total * 100) if total > 0 else 0

        cur.execute(
            f"""
            UPDATE statistics
            SET total_trades = {ph}, wins = {ph}, losses = {ph}, draws = {ph},
                win_rate = {ph}, current_streak = {ph}, best_streak = {ph},
                worst_streak = {ph}, updated_at = {ph}
            WHERE pair = {ph}
            """,
            (total, wins, losses, draws, win_rate, streak, best, worst, datetime.utcnow(), pair),
        )
        conn.commit()
        logger.info("📈 Stats updated for %s: %s (Win rate: %.1f%%)", pair, result, win_rate)
    except Exception as e:
        logger.error("❌ update_statistics failed: %s", e)
        conn.rollback()
    finally:
        conn.close()


def get_statistics(pair):
    """Get statistics for a specific pair."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        cur.execute(f"SELECT * FROM statistics WHERE pair = {ph}", (pair,))
        return cur.fetchone()
    finally:
        conn.close()


def get_overall_statistics():
    """Get statistics for all pairs."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM statistics ORDER BY pair")
        return cur.fetchall()
    finally:
        conn.close()


# ═══════════════════════════════════════════════
#  SETTINGS
# ═══════════════════════════════════════════════

def get_setting(key, default=None):
    """Get a setting value."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        cur.execute(f"SELECT value FROM settings WHERE key = {ph}", (key,))
        row = cur.fetchone()
        if row:
            return row[0] if DATABASE_URL else row['value']
        return default
    finally:
        conn.close()


def set_setting(key, value):
    """Set a setting value (upsert)."""
    conn = get_db_connection()
    cur = conn.cursor()
    ph = _get_placeholder()
    try:
        if DATABASE_URL:
            cur.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = %s
                """,
                (key, value, datetime.utcnow(), value, datetime.utcnow()),
            )
        else:
            cur.execute(
                """
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, datetime.utcnow()),
            )
        conn.commit()
    finally:
        conn.close()


def reset_all_statistics():
    """Reset all statistics to zero."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE statistics
            SET total_trades = 0, wins = 0, losses = 0, draws = 0,
                win_rate = 0, current_streak = 0, best_streak = 0,
                worst_streak = 0, updated_at = CURRENT_TIMESTAMP
        """)
        cur.execute("DELETE FROM trades")
        cur.execute("DELETE FROM pending_signals")
        conn.commit()
        logger.info("🔄 All statistics reset")
    finally:
        conn.close()
