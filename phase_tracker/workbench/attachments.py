from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..archive_files import sha256_file
from .domain import (
    NOT_PROVIDED,
    AttachmentReceipt,
    ResearchRunReceipt,
    WorkflowReference,
)
from .services import _identifier, _now, _write_json
from .store import WorkbenchStore


class WorkbenchAttachmentService:
    """Attach immutable research chronology without creating agent exposure."""

    def __init__(self, project_root: Path):
        self.root = project_root.expanduser().resolve()
        self.store = WorkbenchStore(self.root)

    def attach(
        self,
        run: ResearchRunReceipt,
        workflow_reference: WorkflowReference,
        note: str = "",
    ) -> AttachmentReceipt:
        version_dir = (self.root / workflow_reference.relative_path()).resolve()
        try:
            version_dir.relative_to(self.root)
        except ValueError as error:
            raise ValueError("Attachment target must remain inside the project root") from error
        if not version_dir.is_dir():
            raise ValueError(
                "Attachment target does not exist: "
                f"{workflow_reference.relative_path()}"
            )
        summary_object = (self.root / run.summary_object_path).resolve()
        try:
            summary_object.relative_to(self.store.objects_dir.resolve())
        except ValueError as error:
            raise ValueError("Summary object is outside the Workbench object store") from error
        if sha256_file(summary_object) != run.summary_sha256:
            raise ValueError("The immutable summary object failed hash verification")

        attachment_id = _identifier("wa")
        attached_at = _now()
        parent = version_dir / "user-research"
        destination = parent / attachment_id
        staging = parent / f".{attachment_id}.staging"
        agent_delivery = dict(NOT_PROVIDED)
        provenance: dict[str, object] = {
            "attachment_id": attachment_id,
            "project_id": run.project_id,
            "workflow_position": workflow_reference.to_dict(),
            "artifact_id": run.summary_artifact_id,
            "artifact_sha256": run.summary_sha256,
            "attached_by": "user",
            "attached_at": attached_at,
            "origin_label": "user_research_workbench",
            "pipeline_authority": "none",
            "agent_delivery": agent_delivery,
            "note": note.strip() or "Attached for chronological provenance only.",
        }
        links: dict[str, object] = {
            "run_id": run.run_id,
            "campaign_id": run.campaign_id,
            "run_manifest": run.run_manifest_path,
            "run_provenance": run.provenance_path,
            "summary_object": run.summary_object_path,
            "source_artifacts": [
                source.provenance_dict() for source in run.sources
            ],
            "delivery_statement": (
                "Attachment records user research chronology only. No agent "
                "delivery or exposure event was created."
            ),
        }
        parent.mkdir(parents=True, exist_ok=True)
        staging.mkdir(exist_ok=False)
        try:
            shutil.copyfile(summary_object, staging / "summary.md")
            if sha256_file(staging / "summary.md") != run.summary_sha256:
                raise ValueError("Attached summary copy failed hash verification")
            _write_json(staging / "provenance.json", provenance)
            _write_json(staging / "artifact-links.json", links)
            os.replace(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        receipt = AttachmentReceipt(
            attachment_id=attachment_id,
            artifact_id=run.summary_artifact_id,
            artifact_sha256=run.summary_sha256,
            destination=destination,
            workflow_reference=workflow_reference,
            agent_delivery=agent_delivery,
        )
        try:
            self.store.record_attachment(receipt, run.run_id, attached_at)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        return receipt
