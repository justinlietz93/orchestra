from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..search_engine import ProjectSearchIndex


def utc_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def index_snapshot(index: ProjectSearchIndex) -> dict[str, object]:
    stat = index.db_path.stat()
    connection = sqlite3.connect(index.db_path)
    try:
        node_count, file_count = connection.execute(
            "SELECT COUNT(*), SUM(CASE WHEN kind = 'file' THEN 1 ELSE 0 END) "
            "FROM nodes"
        ).fetchone()
        root_row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'root'"
        ).fetchone()
    finally:
        connection.close()
    return {
        "database_path": index.db_path.relative_to(index.root).as_posix(),
        "database_size_bytes": stat.st_size,
        "database_modified_at": utc_timestamp(stat.st_mtime),
        "database_mtime_ns": stat.st_mtime_ns,
        "indexed_root": str(root_row[0]) if root_row else None,
        "node_count": int(node_count),
        "file_node_count": int(file_count or 0),
    }


def path_metadata(
    root: Path,
    path: str,
    name: str,
    kind: str,
) -> dict[str, object]:
    absolute = root / path
    try:
        stat = absolute.lstat()
    except OSError:
        return {
            "path": path,
            "name": name,
            "kind": kind,
            "exists_at_capture": False,
            "size_bytes": None,
            "modified_at": None,
            "is_symlink": None,
        }
    return {
        "path": path,
        "name": name,
        "kind": kind,
        "exists_at_capture": True,
        "size_bytes": stat.st_size,
        "modified_at": utc_timestamp(stat.st_mtime),
        "is_symlink": absolute.is_symlink(),
    }
