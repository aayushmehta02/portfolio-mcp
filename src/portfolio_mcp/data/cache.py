"""
SQLite-backed cache for Screener.in data.

Key:   NSE ticker  (e.g. "RELIANCE")
Value: JSON-serialised ScreenerData
TTL:   6 hours (configurable via SCREENER_CACHE_TTL_HOURS env var)

Why SQLite?
  • Zero extra infra — works inside the MCP process.
  • Survives across tool invocations within the same day.
  • Single file, easy to inspect or blow away.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from portfolio_mcp.config import get_settings

logger = logging.getLogger(__name__)

# One connection per thread — sqlite3 is not thread-safe in WAL mode by default.
_local = threading.local()

_TTL_HOURS   = 6
_TTL_SECONDS = _TTL_HOURS * 3600


def _db() -> sqlite3.Connection:
    """Return a thread-local SQLite connection, creating the schema on first use."""
    if not hasattr(_local, "conn"):
        db_path = Path(get_settings().db_path)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS screener_cache (
                ticker      TEXT PRIMARY KEY,
                payload     TEXT NOT NULL,
                cached_at   REAL NOT NULL          -- unix timestamp
            )
        """)
        conn.commit()
        _local.conn = conn
    return _local.conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_cached(ticker: str) -> Optional[dict]:
    """
    Return the cached payload dict for `ticker` if it exists and is fresh.
    Returns None if missing or expired.
    """
    try:
        row = _db().execute(
            "SELECT payload, cached_at FROM screener_cache WHERE ticker = ?",
            (ticker.upper(),),
        ).fetchone()
        if row is None:
            return None
        payload_json, cached_at = row
        age = time.time() - cached_at
        if age > _TTL_SECONDS:
            logger.debug("Cache expired for %s (age=%.0fs)", ticker, age)
            return None
        logger.info("Cache HIT for %s (age=%.0fs)", ticker, age)
        return json.loads(payload_json)
    except Exception as exc:
        logger.warning("Cache read failed for %s: %s", ticker, exc)
        return None


def set_cached(ticker: str, data: dict) -> None:
    """Upsert `data` (a dict) into the cache for `ticker`."""
    try:
        _db().execute(
            """
            INSERT INTO screener_cache (ticker, payload, cached_at)
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                payload   = excluded.payload,
                cached_at = excluded.cached_at
            """,
            (ticker.upper(), json.dumps(data), time.time()),
        )
        _db().commit()
        logger.debug("Cached Screener data for %s", ticker)
    except Exception as exc:
        logger.warning("Cache write failed for %s: %s", ticker, exc)


def invalidate(ticker: str) -> None:
    """Force a fresh fetch on the next call for this ticker."""
    try:
        _db().execute(
            "DELETE FROM screener_cache WHERE ticker = ?", (ticker.upper(),)
        )
        _db().commit()
    except Exception as exc:
        logger.warning("Cache invalidate failed for %s: %s", ticker, exc)
