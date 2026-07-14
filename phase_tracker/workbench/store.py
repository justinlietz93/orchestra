from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .domain import AttachmentReceipt, ResearchRunReceipt


class WorkbenchStore:
    def __init__(self, project_root: Path):
        self.project_root = project_root.expanduser().resolve()
        self.control_dir = self.project_root / ".project-handoff" / "workbench"
        self.db_path = self.project_root / ".project-handoff" / "workbench.sqlite3"
        self.objects_dir = self.control_dir / "objects" / "sha256"
        self.runs_dir = self.control_dir / "runs"

    def project_id(self) -> str:
        with self._connection() as connection:
            query = "SELECT value FROM metadata WHERE key = 'project_id'"
            row = connection.execute(query).fetchone()
            if row:
                return str(row[0])
            project_id = f"prj_{uuid.uuid4().hex}"
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES ('project_id', ?)",
                (project_id,),
            )
            return project_id
    def create_campaign(
        self,
        campaign_id: str,
        project_id: str,
        graph_node_path: str,
        objective: str,
        created_at: str,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO campaigns(
                    campaign_id, project_id, graph_node_path, objective,
                    created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, 'user')
                """,
                (
                    campaign_id,
                    project_id,
                    graph_node_path,
                    objective,
                    created_at,
                ),
            )
    def record_run(
        self,
        receipt: ResearchRunReceipt,
        created_at: str,
        manifest_hash: str,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO artifacts(
                    artifact_id, sha256, kind, object_path, created_at
                ) VALUES (?, ?, 'research_summary', ?, ?)
                """,
                (
                    receipt.summary_artifact_id,
                    receipt.summary_sha256,
                    receipt.summary_object_path,
                    created_at,
                ),
            )
            for source in receipt.sources:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO artifacts(
                        artifact_id, sha256, kind, object_path, created_at
                    ) VALUES (?, ?, 'source_snapshot', ?, ?)
                    """,
                    (
                        source.artifact_id,
                        source.sha256,
                        source.object_path,
                        created_at,
                    ),
                )
            connection.execute(
                """
                INSERT INTO runs(
                    run_id, campaign_id, status, created_at, completed_at,
                    summary_artifact_id, manifest_path, provenance_path,
                    manifest_hash, pipeline_authority
                ) VALUES (?, ?, 'completed', ?, ?, ?, ?, ?, ?, 'none')
                """,
                (
                    receipt.run_id,
                    receipt.campaign_id,
                    created_at,
                    created_at,
                    receipt.summary_artifact_id,
                    receipt.run_manifest_path,
                    receipt.provenance_path,
                    manifest_hash,
                ),
            )
            for source in receipt.sources:
                connection.execute(
                    """
                    INSERT INTO run_sources(
                        run_id, artifact_id, source_path, sha256
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        receipt.run_id,
                        source.artifact_id,
                        source.source_path,
                        source.sha256,
                    ),
                )
    def record_attachment(
        self,
        receipt: AttachmentReceipt,
        run_id: str,
        attached_at: str,
    ) -> None:
        reference = receipt.workflow_reference
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO attachments(
                    attachment_id, run_id, artifact_id, artifact_sha256,
                    phase, branch, version, destination, attached_at,
                    pipeline_authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'none')
                """,
                (
                    receipt.attachment_id,
                    run_id,
                    receipt.artifact_id,
                    receipt.artifact_sha256,
                    reference.phase,
                    reference.branch,
                    reference.version,
                    receipt.destination.relative_to(self.project_root).as_posix(),
                    attached_at,
                ),
            )
    def exposure_event_count(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM exposure_events"
            ).fetchone()
        return int(row[0]) if row else 0
    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.control_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            self._create_schema(connection)
            with connection:
                yield connection
        finally:
            connection.close()
    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS metadata(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campaigns(
                campaign_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                graph_node_path TEXT NOT NULL,
                objective TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL CHECK(created_by = 'user')
            );
            CREATE TABLE IF NOT EXISTS artifacts(
                artifact_id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                kind TEXT NOT NULL,
                object_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs(
                run_id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                status TEXT NOT NULL CHECK(status = 'completed'),
                created_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                summary_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
                manifest_path TEXT NOT NULL,
                provenance_path TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                pipeline_authority TEXT NOT NULL CHECK(pipeline_authority = 'none')
            );
            CREATE TABLE IF NOT EXISTS run_sources(
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
                source_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                PRIMARY KEY(run_id, source_path)
            );
            CREATE TABLE IF NOT EXISTS attachments(
                attachment_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
                artifact_sha256 TEXT NOT NULL,
                phase INTEGER NOT NULL,
                branch INTEGER NOT NULL,
                version INTEGER NOT NULL,
                destination TEXT NOT NULL,
                attached_at TEXT NOT NULL,
                pipeline_authority TEXT NOT NULL CHECK(pipeline_authority = 'none')
            );
            CREATE TABLE IF NOT EXISTS exposure_events(
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                role TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO metadata(key, value)
                VALUES ('schema_version', '1');
            """
        )
        immutable_tables = (
            "campaigns",
            "artifacts",
            "runs",
            "run_sources",
            "attachments",
            "exposure_events",
        )
        for table in immutable_tables:
            for action in ("UPDATE", "DELETE"):
                connection.execute(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action.lower()}
                    BEFORE {action} ON {table} BEGIN
                        SELECT RAISE(ABORT, '{table} records are immutable');
                    END
                    """
                )
