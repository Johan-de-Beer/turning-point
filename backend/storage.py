"""Small reproducible SQLite persistence. Capabilities are hashes, never plaintext."""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
import zlib
from pathlib import Path


class Storage:
    def __init__(self, path: str, idle_seconds: int = 86400, idempotency_seconds: int = 86400,
                 max_idempotency_entries: int = 2048, max_idempotency_per_scope: int = 64):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.idempotency_seconds = idempotency_seconds
        self.max_idempotency_entries = max_idempotency_entries
        self.max_idempotency_per_scope = max_idempotency_per_scope
        with self.db:
            self.db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, capability_hash TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots (snapshot_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_runs (run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS idempotency (scope TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(scope,key));
                INSERT OR IGNORE INTO metadata VALUES ('schema_version','1');
            """)
            row = self.db.execute("SELECT value FROM metadata WHERE key='cursor_secret'").fetchone()
            if not row:
                self.db.execute("INSERT INTO metadata VALUES ('cursor_secret',?)", (secrets.token_hex(32),))
            expired = [r[0] for r in self.db.execute("SELECT session_id FROM sessions WHERE updated_at < ?", (time.time() - idle_seconds,))]
            for sid in expired:
                self.db.execute("DELETE FROM snapshots WHERE session_id=?", (sid,))
                self.db.execute("DELETE FROM agent_runs WHERE session_id=?", (sid,))
                self.db.execute("DELETE FROM sessions WHERE session_id=?", (sid,))
            self.db.execute("DELETE FROM idempotency WHERE created_at < ?", (time.time() - idempotency_seconds,))
        self.cursor_secret = bytes.fromhex(self.db.execute("SELECT value FROM metadata WHERE key='cursor_secret'").fetchone()[0])

    def sessions(self):
        return [json.loads(r["payload"]) for r in self.db.execute("SELECT payload FROM sessions")]

    def save_session(self, session_id: str, capability_hash: str, payload: dict):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?)", (session_id, capability_hash, json.dumps(payload), time.time()))

    def save_snapshot(self, snap):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?)", (snap.snapshot_id, snap.session_id, snap.model_dump_json()))

    def get_snapshot(self, snapshot_id: str):
        row = self.db.execute("SELECT payload FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_run(self, run):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO agent_runs VALUES (?,?,?)", (run.run_id, run.session_id, run.model_dump_json()))
            self.db.execute("DELETE FROM agent_runs WHERE session_id=? AND rowid NOT IN (SELECT rowid FROM agent_runs WHERE session_id=? ORDER BY rowid DESC LIMIT 64)", (run.session_id, run.session_id))

    def idempotent(self, scope: str, key: str, fingerprint: str):
        row = self.db.execute("SELECT fingerprint,result,created_at FROM idempotency WHERE scope=? AND key=?", (scope, key)).fetchone()
        if not row:
            return None
        if row["created_at"] < time.time() - self.idempotency_seconds:
            with self.lock, self.db:
                self.db.execute("DELETE FROM idempotency WHERE scope=? AND key=?", (scope, key))
            return None
        if row["fingerprint"] != fingerprint:
            raise ValueError("An Idempotency-Key cannot be reused with a different body")
        result = row["result"]
        # Existing local databases retain readable JSON; new records are compressed
        # to bound storage when responses contain a long observed event prefix.
        return json.loads(zlib.decompress(result) if isinstance(result, bytes) else result)

    def check_idempotency_capacity(self, scope: str):
        with self.lock, self.db:
            self.db.execute("DELETE FROM idempotency WHERE created_at < ?", (time.time() - self.idempotency_seconds,))
        count = self.db.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0]
        scoped = self.db.execute("SELECT COUNT(*) FROM idempotency WHERE scope=?", (scope,)).fetchone()[0]
        if count >= self.max_idempotency_entries or scoped >= self.max_idempotency_per_scope:
            raise OverflowError("Replay request history is full; retry later or start a new replay")

    def save_idempotent(self, scope: str, key: str, fingerprint: str, result: dict):
        with self.lock, self.db:
            compressed = zlib.compress(json.dumps(result, separators=(",", ":")).encode(), level=3)
            self.db.execute("INSERT INTO idempotency VALUES (?,?,?,?,?)", (scope, key, fingerprint, compressed, time.time()))

    def close(self):
        self.db.close()

    def expire_session(self, session_id: str):
        with self.lock, self.db:
            self.db.execute("DELETE FROM snapshots WHERE session_id=?", (session_id,))
            self.db.execute("DELETE FROM agent_runs WHERE session_id=?", (session_id,))
            self.db.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            self.db.execute("DELETE FROM idempotency WHERE scope LIKE 'control:%' AND substr(scope, -?)=?", (len(session_id) + 1, ":" + session_id))

    def reset_derived(self, session_id: str):
        with self.lock, self.db:
            self.db.execute("DELETE FROM snapshots WHERE session_id=?", (session_id,))
            self.db.execute("DELETE FROM agent_runs WHERE session_id=?", (session_id,))

    def cleanup(self, active_session_ids: set[str]):
        with self.lock, self.db:
            self.db.execute("DELETE FROM idempotency WHERE created_at < ?", (time.time() - self.idempotency_seconds,))
            stored_ids = {r[0] for r in self.db.execute("SELECT session_id FROM sessions")}
            for sid in stored_ids - active_session_ids:
                self.expire_session(sid)
            self.db.execute("DELETE FROM snapshots WHERE session_id NOT IN (SELECT session_id FROM sessions)")
            self.db.execute("DELETE FROM agent_runs WHERE session_id NOT IN (SELECT session_id FROM sessions)")
            # Bound WAL growth; truncate after periodic maintenance, never per tick.
        with self.lock:
            self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
