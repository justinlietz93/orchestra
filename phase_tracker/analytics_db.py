"""Derived SQL read-model over Orchestra's ledgers.

Builds a disposable in-memory SQLite database from the append-only journals
(`events.jsonl`, `activity.jsonl`), the export directory listing, and the
attributed judgment stream, then attaches `workbench.sqlite3` read-only.

The journals remain the only source of truth: this database is rebuilt from
scratch on every open/refresh and holds nothing durable. After building,
`PRAGMA query_only = ON` is set so no statement executed against the
connection — including from the query editor — can write to anything.

Saved queries are stored per project in
`.project-handoff/analytics-queries.json` (configuration, not evidence).

Pure module: standard library only, no Qt.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .activity_log import ActivityLog
from .analytics import (
    EXPORT_DIRECTORY,
    WORKBENCH_DB,
    iter_judgments,
    load_workflow_records,
)

SAVED_QUERIES_FILE = Path(".project-handoff") / "analytics-queries.json"
MAX_VIEW_ROWS = 200

SCHEMA = """
CREATE TABLE workflow_events (
    sequence INTEGER PRIMARY KEY,
    event_id TEXT,
    event_type TEXT,
    recorded_at TEXT,
    source_agent TEXT,
    guardian_subject TEXT,
    result TEXT,
    phase INTEGER,
    branch INTEGER,
    version INTEGER,
    archive_action TEXT,
    placement TEXT,
    handoff TEXT
);
CREATE TABLE judgments (
    sequence INTEGER PRIMARY KEY,
    recorded_at TEXT,
    judge TEXT,
    judged TEXT,
    result TEXT,
    is_pass INTEGER,
    is_fail INTEGER,
    attributed INTEGER,
    phase INTEGER,
    branch INTEGER,
    version INTEGER
);
CREATE TABLE activity (
    sequence INTEGER PRIMARY KEY,
    ts TEXT,
    kind TEXT,
    query TEXT,
    provider TEXT,
    mode TEXT,
    ok INTEGER,
    result_count INTEGER,
    duration_ms REAL,
    error TEXT,
    data_json TEXT
);
CREATE TABLE export_files (
    name TEXT,
    prefix TEXT,
    size_bytes INTEGER,
    modified_at TEXT
);
"""


def build_database(root: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)

    records = load_workflow_records(root)
    for sequence, record in enumerate(records):
        coordinate = record.get("coordinate")
        coordinate = coordinate if isinstance(coordinate, dict) else {}
        connection.execute(
            "INSERT INTO workflow_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sequence,
                record.get("event_id"),
                record.get("event_type"),
                record.get("recorded_at"),
                record.get("source_agent"),
                record.get("guardian_subject"),
                record.get("result"),
                coordinate.get("phase"),
                coordinate.get("branch"),
                coordinate.get("version"),
                record.get("archive_action"),
                record.get("placement"),
                record.get("handoff") if isinstance(record.get("handoff"), str) else None,
            ),
        )

    for sequence, judgment in enumerate(iter_judgments(records)):
        record = judgment.get("record", {})
        coordinate = record.get("coordinate")
        coordinate = coordinate if isinstance(coordinate, dict) else {}
        result = judgment["result"]
        connection.execute(
            "INSERT INTO judgments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                sequence,
                record.get("recorded_at"),
                judgment["judging"],
                judgment["judged"],
                result,
                1 if result in ("Pass", "Package produced") else 0,
                1 if result in ("Fail", "Not produced") else 0,
                0 if judgment["judged"] == "unattributed" else 1,
                coordinate.get("phase"),
                coordinate.get("branch"),
                coordinate.get("version"),
            ),
        )

    for sequence, event in enumerate(ActivityLog(root).read_events()):
        data = event.get("data")
        data = data if isinstance(data, dict) else {}
        ok = data.get("ok")
        connection.execute(
            "INSERT INTO activity VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                sequence,
                event.get("ts"),
                event.get("kind"),
                data.get("query"),
                data.get("provider"),
                data.get("mode"),
                None if ok is None else int(bool(ok)),
                data.get("result_count"),
                data.get("duration_ms"),
                data.get("error"),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )

    export_dir = root / EXPORT_DIRECTORY
    if export_dir.exists():
        for path in sorted(export_dir.iterdir()):
            if not path.is_file():
                continue
            stat = path.stat()
            connection.execute(
                "INSERT INTO export_files VALUES (?,?,?,?)",
                (
                    path.name,
                    path.name.split("-", 1)[0],
                    stat.st_size,
                    datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                ),
            )

    workbench_path = root / WORKBENCH_DB
    if workbench_path.exists():
        try:
            connection.execute(
                "ATTACH DATABASE ? AS workbench",
                (f"file:{workbench_path}?mode=ro",),
            )
        except sqlite3.Error:
            pass

    connection.commit()
    connection.execute("PRAGMA query_only = ON")
    return connection


def schema_summary(connection: sqlite3.Connection) -> list[tuple[str, list[str]]]:
    """List (table, columns) across the derived db and attached workbench."""
    tables: list[tuple[str, list[str]]] = []
    for schema in ("main", "workbench"):
        try:
            names = [
                row[0]
                for row in connection.execute(
                    f"SELECT name FROM {schema}.sqlite_master "
                    "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                )
            ]
        except sqlite3.Error:
            continue
        for name in names:
            columns = [
                row[1]
                for row in connection.execute(f'PRAGMA {schema}.table_info("{name}")')
            ]
            qualified = name if schema == "main" else f"workbench.{name}"
            tables.append((qualified, columns))
    return tables


def run_query(
    connection: sqlite3.Connection, sql: str, max_rows: int = MAX_VIEW_ROWS
) -> tuple[list[str], list[tuple], bool]:
    """Execute a query; returns (columns, rows, truncated). Raises sqlite3.Error."""
    cursor = connection.execute(sql)
    columns = [description[0] for description in cursor.description or []]
    rows = cursor.fetchmany(max_rows + 1)
    truncated = len(rows) > max_rows
    return columns, [tuple(row) for row in rows[:max_rows]], truncated


def load_saved_queries(root: Path) -> list[dict]:
    path = root / SAVED_QUERIES_FILE
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    queries = payload.get("queries") if isinstance(payload, dict) else None
    if not isinstance(queries, list):
        return []
    return [
        query
        for query in queries
        if isinstance(query, dict) and query.get("name") and query.get("sql")
    ]


def save_query(root: Path, name: str, sql: str) -> list[dict]:
    """Add or replace a saved query by name; returns the updated list."""
    queries = [
        query for query in load_saved_queries(root) if query["name"] != name
    ]
    queries.append(
        {
            "name": name,
            "sql": sql,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    path = root / SAVED_QUERIES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"queries": queries}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return queries


def delete_query(root: Path, name: str) -> list[dict]:
    queries = [
        query for query in load_saved_queries(root) if query["name"] != name
    ]
    path = root / SAVED_QUERIES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"queries": queries}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return queries
