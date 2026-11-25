from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from app import config
from app.config import ROUTE_POLICY, ROUTE_POLICY_LABEL

# Preserve the historical app.db.DB_PATH test/monkeypatch seam while also
# reading app.config.DB_PATH dynamically for fixtures that patch config.
DB_PATH = config.DB_PATH
_IMPORTED_DB_PATH = config.DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS shifts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  business_day TEXT NOT NULL,
  name TEXT NOT NULL,
  sealed INTEGER NOT NULL DEFAULT 0,
  sealed_at TEXT,
  UNIQUE(business_day, name)
);
CREATE TABLE IF NOT EXISTS chutes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  line_id INTEGER NOT NULL,
  code TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '口门开',
  soft_cap INTEGER NOT NULL DEFAULT 200,
  UNIQUE(line_id, code),
  FOREIGN KEY(line_id) REFERENCES lines(id)
);
CREATE TABLE IF NOT EXISTS route_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dest_code TEXT NOT NULL UNIQUE,
  chute_id INTEGER NOT NULL,
  current_version INTEGER NOT NULL DEFAULT 1,
  note TEXT NOT NULL DEFAULT '',
  FOREIGN KEY(chute_id) REFERENCES chutes(id)
);
CREATE TABLE IF NOT EXISTS scans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  barcode TEXT NOT NULL,
  dest_code TEXT NOT NULL DEFAULT '',
  shift_id INTEGER NOT NULL,
  line_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT '待路由',
  chute_id INTEGER,
  bag_id INTEGER,
  divert_batch_id INTEGER,
  scanned_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  route_policy TEXT NOT NULL DEFAULT 'LOAD_SNAPSHOT',
  planned_chute_id INTEGER,
  snapshot_rule_id INTEGER,
  snapshot_rule_version INTEGER,
  snapshot_at TEXT,
  decided_at TEXT,
  FOREIGN KEY(shift_id) REFERENCES shifts(id),
  FOREIGN KEY(line_id) REFERENCES lines(id),
  FOREIGN KEY(chute_id) REFERENCES chutes(id),
  FOREIGN KEY(planned_chute_id) REFERENCES chutes(id)
);
CREATE TABLE IF NOT EXISTS route_rule_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id INTEGER NOT NULL,
  dest_code TEXT NOT NULL,
  version INTEGER NOT NULL,
  chute_id INTEGER NOT NULL,
  action TEXT NOT NULL,
  changed_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  UNIQUE(rule_id, version),
  FOREIGN KEY(rule_id) REFERENCES route_rules(id),
  FOREIGN KEY(chute_id) REFERENCES chutes(id)
);
CREATE TABLE IF NOT EXISTS route_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id INTEGER NOT NULL,
  chute_id INTEGER,
  action TEXT NOT NULL,
  created_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  policy TEXT NOT NULL DEFAULT 'LOAD_SNAPSHOT',
  FOREIGN KEY(scan_id) REFERENCES scans(id),
  FOREIGN KEY(chute_id) REFERENCES chutes(id)
);
CREATE TABLE IF NOT EXISTS divert_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  shift_id INTEGER NOT NULL,
  code TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT '回流中',
  created_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  FOREIGN KEY(shift_id) REFERENCES shifts(id)
);
CREATE TABLE IF NOT EXISTS bags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  shift_id INTEGER NOT NULL,
  chute_id INTEGER NOT NULL,
  code TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT '集包中',
  sealed_at TEXT,
  note TEXT NOT NULL DEFAULT '',
  FOREIGN KEY(shift_id) REFERENCES shifts(id),
  FOREIGN KEY(chute_id) REFERENCES chutes(id)
);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  ref_id INTEGER,
  action TEXT NOT NULL,
  created_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scans_status ON scans(status);
CREATE INDEX IF NOT EXISTS idx_scans_chute ON scans(chute_id);
CREATE INDEX IF NOT EXISTS idx_route_events_scan ON route_events(scan_id);
CREATE INDEX IF NOT EXISTS idx_audit_ref ON audit_events(kind, ref_id);
"""

_write_lock = threading.RLock()


def active_db_path() -> Path:
    if DB_PATH != _IMPORTED_DB_PATH:
        return Path(DB_PATH)
    return Path(config.DB_PATH)


def connect() -> sqlite3.Connection:
    path = active_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # autocommit mode; db()/write_db() issue explicit BEGIN so rollback boundaries
    # are unambiguous, including for the half-written route-table fixtures.
    conn = sqlite3.connect(
        str(path),
        timeout=15.0,
        check_same_thread=False,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    # The database runs in WAL mode. NORMAL sync keeps rollback/transaction
    # semantics intact while avoiding FULL's fsync cost on every commit.
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def db(immediate: bool = False):
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


@contextmanager
def write_db():
    """Serialize process-local writers and take a SQLite RESERVED lock immediately."""
    with _write_lock:
        with db(immediate=True) as conn:
            yield conn


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(conn: sqlite3.Connection) -> None:
    scan_columns = _column_names(conn, "scans")
    scan_additions = {
        "route_policy": "TEXT NOT NULL DEFAULT 'LOAD_SNAPSHOT'",
        "planned_chute_id": "INTEGER",
        "snapshot_rule_id": "INTEGER",
        "snapshot_rule_version": "INTEGER",
        "snapshot_at": "TEXT",
        "decided_at": "TEXT",
    }
    for name, ddl in scan_additions.items():
        if name not in scan_columns:
            conn.execute(f"ALTER TABLE scans ADD COLUMN {name} {ddl}")

    route_columns = _column_names(conn, "route_rules")
    if "current_version" not in route_columns:
        conn.execute("ALTER TABLE route_rules ADD COLUMN current_version INTEGER NOT NULL DEFAULT 1")

    event_columns = _column_names(conn, "route_events")
    if "policy" not in event_columns:
        conn.execute(
            "ALTER TABLE route_events ADD COLUMN policy TEXT NOT NULL DEFAULT 'LOAD_SNAPSHOT'"
        )

    # This index must be created after ALTER TABLE on legacy databases.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scans_planned_chute ON scans(planned_chute_id)"
    )

    # Historical routed/bagged rows are their own authoritative snapshots. This
    # backfill never derives a planned gate from today's route table for an
    # already-decided item.
    conn.execute(
        """
        UPDATE scans
           SET planned_chute_id = chute_id,
               route_policy = 'LOAD_SNAPSHOT',
               snapshot_at = COALESCE(snapshot_at, decided_at, scanned_at),
               decided_at = COALESCE(decided_at, scanned_at)
         WHERE planned_chute_id IS NULL
           AND chute_id IS NOT NULL
        """
    )
    # Pending legacy scans can only be snapshotted from the route table that is
    # current during this migration; mark that honestly in the snapshot time.
    conn.execute(
        """
        UPDATE scans
           SET planned_chute_id = (
                 SELECT rr.chute_id FROM route_rules rr
                  WHERE rr.dest_code = scans.dest_code
               ),
               snapshot_rule_id = (
                 SELECT rr.id FROM route_rules rr
                  WHERE rr.dest_code = scans.dest_code
               ),
               snapshot_rule_version = (
                 SELECT rr.current_version FROM route_rules rr
                  WHERE rr.dest_code = scans.dest_code
               ),
               snapshot_at = scanned_at,
               route_policy = 'LOAD_SNAPSHOT'
         WHERE planned_chute_id IS NULL
           AND status = '待路由'
           AND dest_code <> ''
           AND EXISTS (SELECT 1 FROM route_rules rr WHERE rr.dest_code = scans.dest_code)
        """
    )

    rules = conn.execute("SELECT id, dest_code, chute_id, current_version FROM route_rules").fetchall()
    for rule in rules:
        exists = conn.execute(
            "SELECT 1 FROM route_rule_versions WHERE rule_id=? AND version=1",
            (rule["id"],),
        ).fetchone()
        if not exists:
            conn.execute(
                """
                INSERT INTO route_rule_versions
                  (rule_id, dest_code, version, chute_id, action, changed_at, note)
                VALUES (?, ?, 1, ?, '历史版本', ?, '迁移补记')
                """,
                (rule["id"], rule["dest_code"], rule["chute_id"], config_now()),
            )

    conn.execute(
        """
        INSERT INTO settings(key, value)
        VALUES ('路由口径', ?), ('路由口径代码', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (ROUTE_POLICY_LABEL, ROUTE_POLICY),
    )

    # Purge any residue from the retired "fake success light" overlay layer.
    # Those keys/bindings could repaint overview counts and audit rows from a
    # settings blob detached from the real load-snapshot ledger; the readers are
    # gone, so dropping the poison here is defence in depth for existing DBs.
    conn.execute(
        "DELETE FROM settings WHERE key IN ('surface_ok', 'surface_last') "
        "OR key LIKE 'snap_surface:%'"
    )
    # The same layer smeared the real scans.note ledger field with this sentinel.
    conn.execute("UPDATE scans SET note='' WHERE note='snap-old'")


def config_now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db() -> None:
    path = active_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            # Some temporary/network filesystems do not support WAL; busy_timeout
            # and the process write lock still provide transaction boundaries.
            pass
        conn.executescript(SCHEMA)
        conn.execute("BEGIN")
        _migrate(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]
