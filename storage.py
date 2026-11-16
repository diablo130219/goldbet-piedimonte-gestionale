"""Database adapter for local SQLite or persistent Neon PostgreSQL.

All customer records and monetary amounts are server-side. In cloud mode DATABASE_URL
must point to Neon; SQLite remains only for local development/testing.
"""
import os
import sqlite3
from pathlib import Path

DATABASE_URL = os.environ.get('DATABASE_URL','').strip()

try:
    from psycopg import IntegrityError as PgIntegrityError
except ImportError:
    PgIntegrityError = sqlite3.IntegrityError
INTEGRITY_ERRORS = (sqlite3.IntegrityError, PgIntegrityError)


class PostgreSQLConnection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        if sql.strip().upper() == 'BEGIN IMMEDIATE':
            sql = 'BEGIN'
        return self.raw.execute(sql.replace('?', '%s'), params)

    def commit(self):
        # With autocommit=True, explicit BEGIN blocks require explicit SQL COMMIT.
        self.raw.execute('COMMIT')

    def rollback(self):
        self.raw.execute('ROLLBACK')

    def close(self):
        self.raw.close()

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self.raw.__exit__(exc_type, exc, tb)


def connect(local_path):
    if DATABASE_URL:
        from psycopg import connect as pg_connect
        from psycopg.rows import dict_row
        raw = pg_connect(DATABASE_URL, autocommit=True, row_factory=dict_row,
                         connect_timeout=12)
        return PostgreSQLConnection(raw)
    path = Path(local_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 15000')
    return conn