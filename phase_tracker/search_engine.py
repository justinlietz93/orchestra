from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .content_extractors import extract_searchable_text, query_terms
from .discovery import BRANCH_PATTERN, VERSION_PATTERN, phase_number_from_name
from .search_query import fields_match_all_phrases, parse_search_query


IGNORED_DIRECTORIES = {".git", ".project-handoff", "node_modules", "__pycache__"}


@dataclass(frozen=True)
class SearchResult:
    node_id: int
    path: str
    name: str
    kind: str
    phase: int | None
    branch: int | None
    version: int | None
    snippet: str
    rank: float
    badges: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelatedFile:
    node_id: int
    path: str
    name: str
    badges: tuple[str, ...] = ()


class ProjectSearchIndex:
    def __init__(self, project_root: Path):
        self.root = project_root.expanduser().resolve()
        self.db_path = self.root / ".project-handoff" / "search.sqlite3"

    def rebuild(self, cancelled: Callable[[], bool] | None = None) -> dict[str, int]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        try:
            self._create_schema(connection)
            connection.execute("DELETE FROM edges")
            connection.execute("DELETE FROM search")
            connection.execute("DELETE FROM nodes")

            node_ids: dict[str, int] = {}
            indexed_files = 0
            skipped_files = 0
            errors = 0
            was_cancelled = False

            root_id = self._insert_node(
                connection,
                ".",
                self.root.name,
                "project",
                None,
                None,
                None,
                None,
                0,
                0,
                self.root.name,
            )
            node_ids["."] = root_id

            for path in self._walk():
                if cancelled and cancelled():
                    was_cancelled = True
                    break
                relative = path.relative_to(self.root).as_posix()
                parent_relative = path.parent.relative_to(self.root).as_posix()
                if parent_relative == "":
                    parent_relative = "."
                parent_id = node_ids.get(parent_relative, root_id)
                phase, branch, version = self._coordinates(path)
                try:
                    stat = path.stat(follow_symlinks=False)
                except OSError:
                    errors += 1
                    continue
                kind = self._kind(path)

                body = ""
                if path.is_file() and not path.is_symlink():
                    try:
                        body = extract_searchable_text(path)
                        if body:
                            indexed_files += 1
                        else:
                            skipped_files += 1
                    except Exception:
                        skipped_files += 1
                        errors += 1

                node_id = self._insert_node(
                    connection,
                    relative,
                    path.name,
                    kind,
                    parent_id,
                    phase,
                    branch,
                    version,
                    stat.st_mtime_ns,
                    stat.st_size if path.is_file() else 0,
                    body,
                )
                node_ids[relative] = node_id
                connection.execute(
                    "INSERT INTO edges(parent_id, child_id, relation) VALUES (?, ?, 'contains')",
                    (parent_id, node_id),
                )

            if was_cancelled:
                connection.rollback()
            else:
                connection.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES ('root', ?)",
                    (str(self.root),),
                )
                connection.commit()
            return {
                "nodes": len(node_ids),
                "indexed_files": indexed_files,
                "skipped_files": skipped_files,
                "errors": errors,
                "cancelled": int(was_cancelled),
            }
        finally:
            connection.close()

    def search(self, query: str, limit: int = 40) -> list[SearchResult]:
        parsed = parse_search_query(query)
        match_query = parsed.fts_expression
        if not match_query or not self.db_path.exists():
            return []
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            phrase_filter = ""
            if parsed.quoted_phrases:
                connection.create_function(
                    "orchestra_phrases_match",
                    3,
                    lambda path, name, body: int(fields_match_all_phrases(
                        parsed.quoted_phrases,
                        path,
                        name,
                        body,
                    )),
                    deterministic=True,
                )
                phrase_filter = (
                    "AND orchestra_phrases_match("
                    "search.path, search.name, search.body) = 1"
                )
            rows = connection.execute(
                f"""
                SELECT n.id, n.path, n.name, n.kind, n.phase, n.branch, n.version,
                       snippet(search, 2, '<mark>', '</mark>', ' … ', 28) AS snippet,
                       bm25(search, 3.5, 5.0, 1.0) AS rank
                FROM search
                JOIN nodes n ON n.id = search.rowid
                WHERE search MATCH ?
                {phrase_filter}
                ORDER BY rank
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()
        finally:
            connection.close()
        attachment_paths = self._attachment_paths()
        return [
            SearchResult(
                node_id=row["id"],
                path=row["path"],
                name=row["name"],
                kind=row["kind"],
                phase=row["phase"],
                branch=row["branch"],
                version=row["version"],
                snippet=row["snippet"] or row["path"],
                rank=float(row["rank"]),
                badges=self._badges(row["path"], attachment_paths),
            )
            for row in rows
        ]

    def related_files(self, node_id: int, limit: int = 30) -> list[RelatedFile]:
        if not self.db_path.exists():
            return []
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            source = connection.execute(
                "SELECT id, phase, branch, version, path FROM nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            if not source:
                return []
            if source["phase"] is None or source["branch"] is None or source["version"] is None:
                return []
            rows = connection.execute(
                """
                SELECT id, path, name
                FROM nodes
                WHERE kind = 'file'
                  AND phase = ? AND branch = ? AND version = ?
                  AND id != ?
                ORDER BY path
                LIMIT ?
                """,
                (
                    source["phase"],
                    source["branch"],
                    source["version"],
                    node_id,
                    limit,
                ),
            ).fetchall()
        finally:
            connection.close()
        attachment_paths = self._attachment_paths()
        return [
            RelatedFile(
                row["id"],
                row["path"],
                row["name"],
                self._badges(row["path"], attachment_paths),
            )
            for row in rows
        ]


    def _attachment_paths(self) -> set[str]:
        db_path = self.root / ".project-handoff" / "workbench.sqlite3"
        if not db_path.exists():
            return set()
        try:
            connection = sqlite3.connect(
                f"file:{db_path}?mode=ro",
                uri=True,
            )
            try:
                rows = connection.execute(
                    "SELECT destination FROM attachments"
                ).fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            return set()
        return {str(row[0]) for row in rows}

    @staticmethod
    def _badges(
        relative_path: str,
        attachment_paths: set[str],
    ) -> tuple[str, ...]:
        parts = Path(relative_path).parts
        if "user-research" not in parts:
            return ()
        position = parts.index("user-research")
        if len(parts) <= position + 1:
            return ()
        attachment = Path(*parts[: position + 2]).as_posix()
        if attachment in attachment_paths:
            return ("USER RESEARCH", "ATTACHED", "NOT PROVIDED")
        return ()

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                parent_id INTEGER,
                phase INTEGER,
                branch INTEGER,
                version INTEGER,
                mtime_ns INTEGER NOT NULL,
                size INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS edges (
                parent_id INTEGER NOT NULL,
                child_id INTEGER NOT NULL,
                relation TEXT NOT NULL,
                PRIMARY KEY (parent_id, child_id, relation)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
                path,
                name,
                body,
                tokenize = 'porter unicode61'
            );
            """
        )

    def _insert_node(
        self,
        connection: sqlite3.Connection,
        path: str,
        name: str,
        kind: str,
        parent_id: int | None,
        phase: int | None,
        branch: int | None,
        version: int | None,
        mtime_ns: int,
        size: int,
        body: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO nodes(path, name, kind, parent_id, phase, branch, version, mtime_ns, size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (path, name, kind, parent_id, phase, branch, version, mtime_ns, size),
        )
        node_id = int(cursor.lastrowid)
        searchable = f"{name}\n{path}\n{body}".strip()
        if searchable:
            connection.execute(
                "INSERT INTO search(rowid, path, name, body) VALUES (?, ?, ?, ?)",
                (node_id, path, name, body),
            )
        return node_id

    def _walk(self) -> Iterable[Path]:
        def visit(directory: Path) -> Iterable[Path]:
            try:
                children = sorted(directory.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
            except OSError:
                return
            for child in children:
                if child.is_dir() and child.name in IGNORED_DIRECTORIES:
                    continue
                yield child
                if child.is_dir() and not child.is_symlink():
                    yield from visit(child)

        yield from visit(self.root)

    def _coordinates(self, path: Path) -> tuple[int | None, int | None, int | None]:
        phase = branch = version = None
        for part in path.relative_to(self.root).parts:
            phase_match = phase_number_from_name(part)
            if phase_match is not None and phase is None:
                phase = phase_match
            branch_match = BRANCH_PATTERN.fullmatch(part)
            if branch_match:
                phase = int(branch_match.group("phase"))
                branch = int(branch_match.group("branch"))
            version_match = VERSION_PATTERN.fullmatch(part)
            if version_match:
                phase = int(version_match.group("phase"))
                branch = int(version_match.group("branch"))
                version = int(version_match.group("version"))
        return phase, branch, version

    def _kind(self, path: Path) -> str:
        if path.is_symlink():
            return "symlink"
        if path.is_file():
            return "file"
        name = path.name
        if VERSION_PATTERN.fullmatch(name):
            return "version"
        if BRANCH_PATTERN.fullmatch(name):
            return "branch"
        if phase_number_from_name(name) is not None:
            return "phase"
        return "directory"
