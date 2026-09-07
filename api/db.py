import os
import sqlite3
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SENTINELOPS_DB", os.path.join(HERE, "sentinelops.db"))
DB_DIR = os.path.dirname(os.path.abspath(DB_PATH))

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,           -- timestamp dari event
    event_type    TEXT    NOT NULL,           -- flow, alert, stats, dsb
    src_ip        TEXT,
    dest_ip       TEXT,
    dest_port     INTEGER,
    proto         TEXT,
    bytes_toserver INTEGER DEFAULT 0,
    bytes_toclient INTEGER DEFAULT 0,
    sid           INTEGER,                    -- diisi hanya untuk event alert
    signature     TEXT,
    severity      INTEGER,
    ingested_at   TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_src  ON events(src_ip);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts);

CREATE TABLE IF NOT EXISTS hosts (
    ip              TEXT PRIMARY KEY,
    first_seen      TEXT,
    last_seen       TEXT,
    risk_score      INTEGER DEFAULT 0,        -- 0-100
    band            TEXT    DEFAULT 'Aman',   -- Aman, Perhatian, Berisiko
    reason          TEXT    DEFAULT '',       -- alasan singkat utk dashboard
    baseline_status TEXT    DEFAULT 'insufficient',
    total_events    INTEGER DEFAULT 0,
    updated_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scores (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ip         TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    band       TEXT NOT NULL,
    computed_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (ip) REFERENCES hosts(ip)
);

CREATE INDEX IF NOT EXISTS idx_scores_ip ON scores(ip);
"""


def get_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        yield conn.cursor()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db_cursor() as cur:
        cur.executescript(SCHEMA)

def insert_events(rows):
    sql = """
        INSERT INTO events
            (ts, event_type, src_ip, dest_ip, dest_port, proto,
             bytes_toserver, bytes_toclient, sid, signature, severity)
        VALUES
            (:ts, :event_type, :src_ip, :dest_ip, :dest_port, :proto,
             :bytes_toserver, :bytes_toclient, :sid, :signature, :severity)
    """
    with db_cursor() as cur:
        cur.executemany(sql, rows)
        return cur.rowcount
    
def upsert_host(ip, risk_score, band, baseline_status, total_events,
                reason='', first_seen=None, last_seen=None):
    sql = """
        INSERT INTO hosts (ip, first_seen, last_seen, risk_score, band,
                           reason, baseline_status, total_events, updated_at)
        VALUES (:ip, :first_seen, :last_seen, :risk_score, :band,
                :reason, :baseline_status, :total_events, datetime('now'))
        ON CONFLICT(ip) DO UPDATE SET
            last_seen       = COALESCE(:last_seen, last_seen),
            risk_score      = :risk_score,
            band            = :band,
            reason          = :reason,
            baseline_status = :baseline_status,
            total_events    = :total_events,
            updated_at      = datetime('now')
    """
    params = {
        "ip": ip, "first_seen": first_seen, "last_seen": last_seen,
        "risk_score": risk_score, "band": band, "reason": reason,
        "baseline_status": baseline_status, "total_events": total_events,
    }
    with db_cursor() as cur:
        cur.execute(sql, params)

def get_hosts():
    with db_cursor() as cur:
        cur.execute(
            "SELECT ip, risk_score, band, reason, baseline_status, "
            "total_events, last_seen FROM hosts ORDER BY risk_score DESC"
        )
        return [dict(r) for r in cur.fetchall()]


def get_host(ip):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM hosts WHERE ip = ?", (ip,))
        host = cur.fetchone()
        if host is None:
            return None
        cur.execute(
            "SELECT risk_score, band, computed_at FROM scores "
            "WHERE ip = ? ORDER BY computed_at DESC LIMIT 50",
            (ip,),
        )
        trend = [dict(r) for r in cur.fetchall()]
        result = dict(host)
        result["trend"] = trend
        return result

def record_score(ip, risk_score, band):
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO scores (ip, risk_score, band) VALUES (?, ?, ?)",
            (ip, risk_score, band),
        )

if __name__ == "__main__":
    init_db()
    print(f"[ok] Skema dibuat/diverifikasi di {DB_PATH}")
    with db_cursor() as cur:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
    print(f"[ok] Tabel: {', '.join(tables)}")
