"""Very small SQLite helper (plain sqlite3, no ORM).

A new connection is opened per call because the background worker threads
and the Flask request threads must not share one connection.
"""
import os
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    event_name      TEXT NOT NULL,
    issued_by       TEXT NOT NULL,
    issue_date      TEXT NOT NULL,
    status          TEXT NOT NULL,
    total           INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS certificates (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES jobs(id),
    position        INTEGER NOT NULL,       -- index of the recipient in the request
    name            TEXT,
    email           TEXT,
    course          TEXT,
    status          TEXT NOT NULL,          -- PENDING / SUCCESS / FAILED
    error           TEXT,
    file_path       TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cert_job ON certificates(job_id);
"""


@contextmanager
def get_conn(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path):
    folder = os.path.dirname(db_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)
