"""SQLCipher-encrypted local mapping database.

Stores the global placeholder<->real-value mapping, the persistent custom
term list, shared category-toggle settings, monotonic placeholder counters,
and a hash-chained (tamper-evident) audit log.

Fail-closed: any open/verify error (wrong passphrase, corrupt or locked file)
raises DatabaseError; callers must not proceed without a working DB.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import sqlcipher3

from .categories import CATEGORY_DEFAULTS, prefix_for
from .util import normalize

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    placeholder TEXT NOT NULL UNIQUE,
    real_value TEXT NOT NULL,
    real_value_norm TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    first_seen_doc TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS counters (
    prefix TEXT PRIMARY KEY,
    next INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS custom_terms (
    id INTEGER PRIMARY KEY,
    term TEXT NOT NULL,
    term_norm TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    doc TEXT,
    detail TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
"""

GENESIS_HASH = "0" * 64


class DatabaseError(Exception):
    """DB cannot be opened/used. Callers must fail closed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MappingDB:
    def __init__(
        self,
        path: Path,
        passphrase: str,
        create: bool = True,
        check_same_thread: bool = True,
    ):
        """`check_same_thread=False` is for the local web server, whose sync
        endpoints run in FastAPI's threadpool — a single logical session can
        legitimately span multiple OS threads there. The CLI stays
        single-threaded and keeps the default (stricter) sqlite behavior."""
        self.path = Path(path)
        if not create and not self.path.exists():
            raise DatabaseError(
                f"Database not found at {self.path}. Run 'local-redact init' first."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlcipher3.connect(
                str(self.path), check_same_thread=check_same_thread
            )
            # Parameter binding is not supported for PRAGMA; escape single
            # quotes per SQL rules. SQLCipher applies its own PBKDF2 to this.
            escaped = passphrase.replace("'", "''")
            self._conn.execute(f"PRAGMA key = '{escaped}'")
            # Probe the key now: connect() is lazy, and a wrong key surfaces
            # as sqlite errors OR MemoryError (sqlcipher3 quirk) on first
            # access. Fail closed on anything the probe raises.
            self._conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        except Exception as exc:
            try:
                self._conn.close()
            except Exception:
                pass
            raise DatabaseError(
                "Cannot open mapping DB (wrong passphrase, or file locked/corrupt). "
                "Refusing to continue."
            ) from exc
        self._closed = False

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        if not self._closed:
            self._conn.close()
            self._closed = True

    def __enter__(self) -> "MappingDB":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # -- entities / placeholders ------------------------------------------

    def get_or_create_placeholder(
        self, real_value: str, entity_type: str, doc: str | None
    ) -> str:
        """One stable placeholder per real value, forever."""
        norm = normalize(real_value)
        row = self._conn.execute(
            "SELECT placeholder FROM entities WHERE real_value_norm = ?", (norm,)
        ).fetchone()
        if row:
            return row[0]
        prefix = prefix_for(entity_type)
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO counters (prefix, next) VALUES (?, 1) "
                "ON CONFLICT(prefix) DO UPDATE SET next = next + 1 "
                "RETURNING next - 1",
                (prefix,),
            )
            n = cur.fetchone()[0]
            placeholder = f"{prefix}_{n:05d}"
            self._conn.execute(
                "INSERT INTO entities "
                "(placeholder, real_value, real_value_norm, entity_type, "
                " first_seen_doc, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (placeholder, real_value, norm, entity_type, doc, _utcnow()),
            )
        return placeholder

    def placeholder_map(self) -> dict[str, str]:
        """placeholder -> real value, for reveal."""
        return {
            ph: real
            for ph, real in self._conn.execute(
                "SELECT placeholder, real_value FROM entities"
            )
        }

    def entity_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]

    # -- custom terms ------------------------------------------------------

    def add_term(self, term: str) -> bool:
        """Returns True if newly added, False if already present."""
        term = term.strip()
        if not term:
            raise ValueError("empty custom term")
        with self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO custom_terms (term, term_norm, created_at) "
                "VALUES (?, ?, ?)",
                (term, normalize(term), _utcnow()),
            )
        return cur.rowcount > 0

    def remove_term(self, term: str) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM custom_terms WHERE term_norm = ?", (normalize(term),)
            )
        return cur.rowcount > 0

    def list_terms(self) -> list[str]:
        return [
            r[0]
            for r in self._conn.execute("SELECT term FROM custom_terms ORDER BY term")
        ]

    # -- settings (category toggles, shared by both front ends) ------------

    def get_toggles(self) -> dict[str, bool]:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = 'category_toggles'"
        ).fetchone()
        stored = json.loads(row[0]) if row else {}
        merged = dict(CATEGORY_DEFAULTS)
        for k, v in stored.items():
            if k in merged:
                merged[k] = bool(v)
        return merged

    def set_toggle(self, category: str, enabled: bool) -> None:
        if category not in CATEGORY_DEFAULTS:
            raise ValueError(f"unknown category: {category}")
        toggles = self.get_toggles()
        toggles[category] = enabled
        with self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES ('category_toggles', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (json.dumps(toggles),),
            )

    # -- audit log (append-only, hash-chained) ------------------------------

    def log_action(
        self, action: str, doc: str | None = None, detail: dict | None = None
    ) -> str:
        """Append an audit entry. `detail` must never contain raw content —
        pass counts and hashes only."""
        ts = _utcnow()
        prev = self._conn.execute(
            "SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = prev[0] if prev else GENESIS_HASH
        detail_json = json.dumps(detail or {}, sort_keys=True)
        payload = f"{ts}|{action}|{doc or ''}|{detail_json}|{prev_hash}"
        entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self._conn:
            self._conn.execute(
                "INSERT INTO audit_log (ts, action, doc, detail, prev_hash, hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, action, doc, detail_json, prev_hash, entry_hash),
            )
        return entry_hash

    def audit_entries(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, ts, action, doc, detail, prev_hash, hash "
            "FROM audit_log ORDER BY id"
        ).fetchall()
        return [
            {
                "id": r[0],
                "ts": r[1],
                "action": r[2],
                "doc": r[3],
                "detail": json.loads(r[4]),
                "prev_hash": r[5],
                "hash": r[6],
            }
            for r in rows
        ]

    def verify_audit_chain(self) -> bool:
        prev_hash = GENESIS_HASH
        for e in self.audit_entries():
            if e["prev_hash"] != prev_hash:
                return False
            payload = (
                f"{e['ts']}|{e['action']}|{e['doc'] or ''}|"
                f"{json.dumps(e['detail'], sort_keys=True)}|{prev_hash}"
            )
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != e["hash"]:
                return False
            prev_hash = e["hash"]
        return True

    # -- wipe ---------------------------------------------------------------

    def wipe(self) -> None:
        """Manual 'wipe everything': mapping, terms, settings, counters.
        Audit log is also cleared and restarted with a wipe entry so the
        chain reflects post-wipe state only."""
        with self._conn:
            for table in (
                "entities",
                "counters",
                "custom_terms",
                "settings",
                "audit_log",
            ):
                self._conn.execute(f"DELETE FROM {table}")
        self.log_action("wipe", detail={"note": "all mappings, terms, settings cleared"})
