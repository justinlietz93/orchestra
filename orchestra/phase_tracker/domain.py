from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class Agent(StrEnum):
    OPERATOR = "Operator"
    GUARDIAN = "Guardian"
    AUDITOR = "Auditor"


class ArchiveAction(StrEnum):
    CONTINUE = "continue"
    NEW_BRANCH = "new_branch"
    NEW_PHASE = "new_phase"


class ProjectStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


@dataclass(frozen=True)
class Coordinate:
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> Coordinate | None:
        if not value:
            return None
        return cls(
            phase=int(value["phase"]),
            branch=int(value["branch"]),
            version=int(value["version"]),
            phase_dir=str(value["phase_dir"]),
        )


@dataclass(frozen=True)
class ArchiveTarget:
    coordinate: Coordinate
    action: ArchiveAction
    phase_path: Path
    branch_path: Path
    version_path: Path


@dataclass
class WorkflowState:
    active_agent: Agent = Agent.OPERATOR
    guardian_subject: Agent | None = None
    auditor_revision: bool = False
    status: ProjectStatus = ProjectStatus.IN_PROGRESS
    last_coordinate: Coordinate | None = None
    last_event_id: str | None = None
    last_manifest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_agent": self.active_agent.value,
            "guardian_subject": (
                self.guardian_subject.value if self.guardian_subject else None
            ),
            "auditor_revision": self.auditor_revision,
            "status": self.status.value,
            "last_coordinate": (
                self.last_coordinate.to_dict() if self.last_coordinate else None
            ),
            "last_event_id": self.last_event_id,
            "last_manifest": self.last_manifest,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WorkflowState:
        subject = value.get("guardian_subject")
        return cls(
            active_agent=Agent(value.get("active_agent", Agent.OPERATOR.value)),
            guardian_subject=Agent(subject) if subject else None,
            auditor_revision=bool(value.get("auditor_revision", False)),
            status=ProjectStatus(
                value.get("status", ProjectStatus.IN_PROGRESS.value)
            ),
            last_coordinate=Coordinate.from_dict(value.get("last_coordinate")),
            last_event_id=value.get("last_event_id"),
            last_manifest=value.get("last_manifest"),
        )


@dataclass(frozen=True)
class Transition:
    previous_agent: Agent
    result: str
    next_state: WorkflowState
    handoff: str


@dataclass(frozen=True)
class ArchiveReceipt:
    event_id: str
    destination: Path
    coordinate: Coordinate
    next_state: WorkflowState
    handoff: str
    artifact_count: int
    created_coordinate: bool
    warning: str | None = None
