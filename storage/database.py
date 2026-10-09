import sqlite3
import threading
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    frames      INTEGER DEFAULT 0,
    total_count INTEGER DEFAULT 0,
    in_count    INTEGER DEFAULT 0,
    out_count   INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS vehicles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    track_id      INTEGER NOT NULL,
    vehicle_type  TEXT NOT NULL,
    confidence    REAL,
    first_seen    REAL,
    last_seen     REAL,
    frames_seen   INTEGER,
    direction     TEXT,
    counted       INTEGER DEFAULT 0,
    crossed_at    REAL,
    snapshot_path TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE(session_id, track_id)
);
CREATE INDEX IF NOT EXISTS idx_vehicles_type ON vehicles(vehicle_type);
CREATE INDEX IF NOT EXISTS idx_vehicles_track ON vehicles(track_id);
"""

VEHICLE_COLUMNS = ("track_id", "vehicle_type", "confidence", "first_seen", "last_seen",
                   "frames_seen", "direction", "counted", "crossed_at", "snapshot_path")


class Database:
    """SQLite storage shared by the processing thread (writes) and the UI (reads)."""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # ---------- sessions ----------
    def create_session(self, source: str) -> int:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO sessions (source, started_at) VALUES (?, ?)",
                (source, datetime.now().isoformat(timespec="seconds")))
            self.conn.commit()
            return cur.lastrowid

    def update_session(self, session_id: int, *, frames: int, total: int,
                       in_count: int, out_count: int, ended: bool = False) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE sessions SET frames=?, total_count=?, in_count=?, out_count=?"
                + (", ended_at=?" if ended else "") + " WHERE id=?",
                (frames, total, in_count, out_count,
                 *( [datetime.now().isoformat(timespec="seconds")] if ended else []), session_id))
            self.conn.commit()

    def list_sessions(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM sessions ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: int) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            self.conn.commit()

    # ---------- vehicles ----------
    def upsert_vehicles(self, session_id: int, rows: list[dict]) -> None:
        if not rows:
            return
        now = datetime.now().isoformat(timespec="seconds")
        cols = ", ".join(VEHICLE_COLUMNS)
        marks = ", ".join("?" for _ in VEHICLE_COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in VEHICLE_COLUMNS if c != "track_id")
        sql = (f"INSERT INTO vehicles (session_id, {cols}, created_at) VALUES (?, {marks}, ?) "
               f"ON CONFLICT(session_id, track_id) DO UPDATE SET {updates}")
        params = [(session_id, *(r[c] for c in VEHICLE_COLUMNS), now) for r in rows]
        with self.lock:
            self.conn.executemany(sql, params)
            self.conn.commit()

    def search_vehicles(self, text: str = "", vehicle_type: str | None = None,
                        direction: str | None = None, counted_only: bool = False,
                        session_id: int | None = None, limit: int = 5000) -> list[dict]:
        """Search by ID ("42", "#42") or type text ("truck"), plus optional filters."""
        where, params = [], []
        text = (text or "").strip().lstrip("#")
        if text:
            if text.isdigit():
                where.append("v.track_id = ?")
                params.append(int(text))
            else:
                where.append("LOWER(v.vehicle_type) LIKE ?")
                params.append(f"%{text.lower()}%")
        if vehicle_type:
            where.append("v.vehicle_type = ?")
            params.append(vehicle_type)
        if direction:
            where.append("v.direction = ?")
            params.append(direction)
        if counted_only:
            where.append("v.counted = 1")
        if session_id is not None:
            where.append("v.session_id = ?")
            params.append(session_id)
        sql = ("SELECT v.*, s.source FROM vehicles v JOIN sessions s ON s.id = v.session_id"
               + (" WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY v.session_id DESC, v.track_id DESC LIMIT ?")
        params.append(limit)
        with self.lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_vehicle(self, session_id: int, track_id: int) -> dict | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT v.*, s.source FROM vehicles v JOIN sessions s ON s.id = v.session_id "
                "WHERE v.session_id=? AND v.track_id=?", (session_id, track_id)).fetchone()
        return dict(row) if row else None

    def type_totals(self, session_id: int | None = None, counted_only: bool = True) -> dict[str, int]:
        where, params = [], []
        if counted_only:
            where.append("counted = 1")
        if session_id is not None:
            where.append("session_id = ?")
            params.append(session_id)
        sql = ("SELECT vehicle_type, COUNT(*) FROM vehicles"
               + (" WHERE " + " AND ".join(where) if where else "") + " GROUP BY vehicle_type")
        with self.lock:
            return {t: n for t, n in self.conn.execute(sql, params).fetchall()}

    def close(self) -> None:
        with self.lock:
            self.conn.close()
