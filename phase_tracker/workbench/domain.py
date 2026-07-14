from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


NOT_PROVIDED = {
    "operator": "not_provided",
    "guardian": "not_provided",
    "auditor": "not_provided",
}
PIPELINE_ROLES = ("operator", "guardian", "auditor")
EXCLUDED_HANDOFF_DIRECTORY = "user-research"


class HandoffPackageExclusionPolicy:
    """Default-deny Workbench attachments in every agent handoff role."""

    def __init__(self, project_root: Path):
        self.root = project_root.expanduser().resolve()

    def filter_default(
        self,
        candidates: Iterable[Path],
        target_role: str,
    ) -> tuple[Path, ...]:
        role = target_role.lower()
        if role not in PIPELINE_ROLES:
            raise ValueError(f"Unknown pipeline role: {target_role}")
        included: list[Path] = []
        for candidate in candidates:
            relative = self._relative(candidate)
            if EXCLUDED_HANDOFF_DIRECTORY not in relative.parts:
                included.append(candidate)
        return tuple(included)

    def is_default_included(self, candidate: Path, target_role: str) -> bool:
        return bool(self.filter_default((candidate,), target_role))

    def _relative(self, candidate: Path) -> Path:
        path = candidate.expanduser()
        resolved = (
            path.resolve()
            if path.is_absolute()
            else (self.root / path).resolve()
        )
        try:
            return resolved.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Handoff candidates must be inside the project root: {candidate}"
            ) from error


@dataclass(frozen=True)
class WorkflowReference:
    phase: int
    branch: int
    version: int
    phase_dir: str

    @property
    def branch_name(self) -> str:
        return f"p{self.phase}-b{self.branch}"

    @property
    def version_name(self) -> str:
        return f"{self.branch_name}-v{self.version}"

    def relative_path(self) -> Path:
        return Path(self.phase_dir) / self.branch_name / self.version_name

    def to_dict(self) -> dict[str, int]:
        return {
            "phase": self.phase,
            "branch": self.branch,
            "version": self.version,
        }


@dataclass(frozen=True)
class SourceSnapshot:
    artifact_id: str
    source_path: str
    sha256: str
    size: int
    object_path: str
    extracted_text: str
    extraction_note: str | None = None

    def provenance_dict(self) -> dict[str, str | int]:
        value: dict[str, str | int] = {
            "artifact_id": self.artifact_id,
            "source_path": self.source_path,
            "sha256": self.sha256,
            "size": self.size,
            "object_path": self.object_path,
        }
        if self.extraction_note:
            value["extraction_note"] = self.extraction_note
        return value


@dataclass(frozen=True)
class ResearchRunReceipt:
    project_id: str
    campaign_id: str
    run_id: str
    graph_node_path: str
    summary_artifact_id: str
    summary_sha256: str
    summary_text: str
    summary_object_path: str
    run_manifest_path: str
    provenance_path: str
    sources: tuple[SourceSnapshot, ...]


@dataclass(frozen=True)
class AttachmentReceipt:
    attachment_id: str
    artifact_id: str
    artifact_sha256: str
    destination: Path
    workflow_reference: WorkflowReference
    agent_delivery: dict[str, str]


@dataclass(frozen=True)
class RunPolicy:
    max_files: int = 64
    max_excerpt_chars_per_file: int = 1600
    max_summary_source_chars: int = 16000

    def to_dict(self) -> dict[str, object]:
        return {
            "budget": {
                "max_files": self.max_files,
                "max_excerpt_chars_per_file": self.max_excerpt_chars_per_file,
                "max_summary_source_chars": self.max_summary_source_chars,
            },
            "privacy": {
                "mode": "internal_only",
                "external_provider_access": False,
            },
            "snapshot": {"mode": "exact_bytes", "symlinks": "rejected"},
            "reproducibility": "byte",
        }
