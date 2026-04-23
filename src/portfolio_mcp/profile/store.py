"""
User profile persistence via SQLite.
One profile per user_id. Profiles seed the future recommendation engine.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from portfolio_mcp.config import get_settings
from portfolio_mcp.schemas import UserProfile


class ProfileStore:
    def __init__(self):
        self._db_path = Path(get_settings().db_path)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id    TEXT PRIMARY KEY,
                    payload    TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def save(self, profile: UserProfile) -> None:
        profile.updated_at = datetime.utcnow()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT INTO user_profiles (user_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    payload    = excluded.payload,
                    updated_at = excluded.updated_at
            """, (profile.user_id, profile.model_dump_json(), profile.updated_at.isoformat()))
            conn.commit()

    def load(self, user_id: str) -> Optional[UserProfile]:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM user_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            return None
        return UserProfile.model_validate_json(row[0])

    def delete(self, user_id: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))
            conn.commit()


_store: Optional[ProfileStore] = None

def get_profile_store() -> ProfileStore:
    global _store
    if _store is None:
        _store = ProfileStore()
    return _store
