from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .artifacts import (
    ArtifactSnapshotService,
    ContentAddressedStore,
    InternalCorpusConnector,
    ResearchSummaryService,
)
from .domain import (
    NOT_PROVIDED,
    ResearchRunReceipt,
    RunPolicy,
)
from .store import WorkbenchStore


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _identifier(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:12]}"


def _canonical_hash(value: dict[str, object]) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


class ResearchCampaignService:
    def __init__(self, project_root: Path):
        self.store = WorkbenchStore(project_root)

    def create(self, objective: str, graph_node_path: str) -> tuple[str, str, str]:
        objective = objective.strip()
        if not objective:
            raise ValueError("Enter a research objective")
        graph_node_path = graph_node_path.strip() or "."
        project_id = self.store.project_id()
        campaign_id = _identifier("rc")
        created_at = _now()
        self.store.create_campaign(
            campaign_id,
            project_id,
            graph_node_path,
            objective,
            created_at,
        )
        return project_id, campaign_id, created_at


class ResearchRunService:
    def __init__(self, project_root: Path, policy: RunPolicy | None = None):
        self.root = project_root.expanduser().resolve()
        self.policy = policy or RunPolicy()
        self.store = WorkbenchStore(self.root)
        snapshots = ArtifactSnapshotService(self.root, self.policy)
        self.connector = InternalCorpusConnector(snapshots)
        self.summaries = ResearchSummaryService(self.policy)
        self.objects = ContentAddressedStore(self.store)

    def complete_internal_run(
        self,
        project_id: str,
        campaign_id: str,
        objective: str,
        graph_node_path: str,
        selected_paths: Iterable[Path],
    ) -> ResearchRunReceipt:
        created_at = _now()
        run_id = _identifier("rr")
        sources = self.connector.collect(selected_paths)
        summary = self.summaries.render(objective, graph_node_path, sources)
        summary_bytes = summary.encode("utf-8")
        summary_sha, summary_object_path = self.objects.put_bytes(summary_bytes)
        summary_artifact_id = f"art_summary_{summary_sha[:24]}"

        manifest: dict[str, object] = {
            "run_id": run_id,
            "campaign_id": campaign_id,
            "project_id": project_id,
            "created_by": "user",
            "created_at": created_at,
            "completed_at": created_at,
            "status": "completed",
            "supersedes_run_id": None,
            "plan": {
                "mode": "internal_only",
                "graph_node_path": graph_node_path,
                "selected_artifacts": [source.source_path for source in sources],
            },
            "policies": self.policy.to_dict(),
            "artifacts": [
                summary_artifact_id,
                *[source.artifact_id for source in sources],
            ],
            "pipeline_authority": "none",
            "manifest_hash": None,
        }
        manifest_hash = _canonical_hash(manifest)
        manifest["manifest_hash"] = manifest_hash

        provenance: dict[str, object] = {
            "schema_version": 1,
            "origin_label": "user_research_workbench",
            "created_by": "user",
            "run_id": run_id,
            "campaign_id": campaign_id,
            "project_id": project_id,
            "graph_node_path": graph_node_path,
            "source_snapshots": [
                source.provenance_dict() for source in sources
            ],
            "summary": {
                "artifact_id": summary_artifact_id,
                "sha256": summary_sha,
                "object_path": summary_object_path,
            },
            "states": {
                "created": True,
                "attached": False,
                "provided_to_agent": False,
                "acknowledged_by_agent": False,
                "relied_on_by_agent": False,
                "audited": False,
                "adopted": False,
                "published": False,
            },
            "agent_delivery": dict(NOT_PROVIDED),
            "pipeline_authority": "none",
        }
        links: dict[str, object] = {
            "summary_object": summary_object_path,
            "source_objects": [
                {
                    "artifact_id": source.artifact_id,
                    "source_path": source.source_path,
                    "sha256": source.sha256,
                    "object_path": source.object_path,
                }
                for source in sources
            ],
        }
        final_dir = self.store.runs_dir / run_id
        staging = self.store.control_dir / f".staging-{run_id}"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            _write_json(staging / "run.json", manifest)
            _write_json(staging / "provenance.json", provenance)
            _write_json(staging / "artifact-links.json", links)
            self.store.runs_dir.mkdir(parents=True, exist_ok=True)
            os.replace(staging, final_dir)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        run_manifest_path = (final_dir / "run.json").relative_to(
            self.root
        ).as_posix()
        provenance_path = (final_dir / "provenance.json").relative_to(
            self.root
        ).as_posix()
        receipt = ResearchRunReceipt(
            project_id=project_id,
            campaign_id=campaign_id,
            run_id=run_id,
            graph_node_path=graph_node_path,
            summary_artifact_id=summary_artifact_id,
            summary_sha256=summary_sha,
            summary_text=summary,
            summary_object_path=summary_object_path,
            run_manifest_path=run_manifest_path,
            provenance_path=provenance_path,
            sources=sources,
        )
        try:
            self.store.record_run(receipt, created_at, manifest_hash)
        except Exception:
            shutil.rmtree(final_dir, ignore_errors=True)
            raise
        return receipt


class ResearchWorkbenchService:
    def __init__(self, project_root: Path, policy: RunPolicy | None = None):
        self.root = project_root.expanduser().resolve()
        self.campaigns = ResearchCampaignService(self.root)
        self.runs = ResearchRunService(self.root, policy)

    def create_campaign_run(
        self,
        objective: str,
        graph_node_path: str,
        selected_paths: Iterable[Path],
    ) -> ResearchRunReceipt:
        project_id, campaign_id, _created_at = self.campaigns.create(
            objective, graph_node_path
        )
        return self.runs.complete_internal_run(
            project_id,
            campaign_id,
            objective,
            graph_node_path,
            selected_paths,
        )
