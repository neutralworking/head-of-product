"""SQLite-backed cross-run context store for Head of Product."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "output" / "hop.db"

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _init_tables(_local.conn)
    return _local.conn


def _init_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            data TEXT NOT NULL,
            status TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_scans_repo_ts ON scans(repo, timestamp DESC);

        CREATE TABLE IF NOT EXISTS digests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            data TEXT NOT NULL,
            portfolio_status TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_digests_ts ON digests(timestamp DESC);

        CREATE TABLE IF NOT EXISTS todo_cache (
            repo TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
    """)
    conn.commit()


def get_previous_scan(repo: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT data FROM scans WHERE repo = ? ORDER BY timestamp DESC LIMIT 1",
        (repo,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["data"])


def save_scan(repo: str, data: dict) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    status = data.get("status", "unknown")
    conn.execute(
        "INSERT INTO scans (repo, timestamp, data, status) VALUES (?, ?, ?, ?)",
        (repo, now, json.dumps(data), status),
    )
    conn.commit()


def get_previous_digest() -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT data FROM digests ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["data"])


def save_digest(data: dict) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    portfolio_status = data.get("portfolio_status", "unknown")
    conn.execute(
        "INSERT INTO digests (timestamp, data, portfolio_status) VALUES (?, ?, ?)",
        (now, json.dumps(data), portfolio_status),
    )
    conn.commit()


def get_cached_todos(repo: str, max_age_minutes: int = 480) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT data, fetched_at FROM todo_cache WHERE repo = ?",
        (repo,),
    ).fetchone()
    if row is None:
        return None
    fetched_at = datetime.fromisoformat(row["fetched_at"])
    age_minutes = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 60
    if age_minutes > max_age_minutes:
        return None
    return json.loads(row["data"])


def cache_todos(repo: str, data: dict) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO todo_cache (repo, data, fetched_at) VALUES (?, ?, ?)"
        " ON CONFLICT(repo) DO UPDATE SET data = excluded.data, fetched_at = excluded.fetched_at",
        (repo, json.dumps(data), now),
    )
    conn.commit()
