"""
Encrypted token persistence using SQLite.
Tokens are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256).
"""
from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from portfolio_mcp.config import get_settings
from portfolio_mcp.schemas import Broker, SessionToken


def _derive_fernet(secret_key: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"portfolio_mcp_salt",  # static salt — fine for local token store
        iterations=100_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return Fernet(key)


class TokenStore:
    def __init__(self):
        settings = get_settings()
        self._db_path = Path(settings.db_path)
        self._fernet = _derive_fernet(settings.secret_key)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS broker_tokens (
                    broker      TEXT PRIMARY KEY,
                    payload     TEXT NOT NULL,        -- encrypted JSON
                    updated_at  TEXT NOT NULL
                )
            """)
            conn.commit()

    def save(self, token: SessionToken) -> None:
        raw = token.model_dump_json()
        encrypted = self._fernet.encrypt(raw.encode()).decode()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT INTO broker_tokens (broker, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(broker) DO UPDATE SET
                    payload    = excluded.payload,
                    updated_at = excluded.updated_at
            """, (token.broker.value, encrypted, datetime.utcnow().isoformat()))
            conn.commit()

    def load(self, broker: Broker) -> SessionToken | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM broker_tokens WHERE broker = ?",
                (broker.value,)
            ).fetchone()
        if row is None:
            return None
        decrypted = self._fernet.decrypt(row[0].encode()).decode()
        return SessionToken.model_validate_json(decrypted)

    def delete(self, broker: Broker) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM broker_tokens WHERE broker = ?", (broker.value,))
            conn.commit()

    def list_connected(self) -> list[Broker]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT broker FROM broker_tokens").fetchall()
        return [Broker(row[0]) for row in rows]


# Module-level singleton
_store: TokenStore | None = None


def get_token_store() -> TokenStore:
    global _store
    if _store is None:
        _store = TokenStore()
    return _store
