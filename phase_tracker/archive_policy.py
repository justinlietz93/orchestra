from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .discovery import ProjectIndex, compute_target, current_target
from .domain import Agent, ArchiveAction, ArchiveTarget, Coordinate, WorkflowState


class PlacementMode(StrEnum):
    CREATE = "create"
    APPEND = "append"


@dataclass(frozen=True)
class ArchivePlacement:
    mode: PlacementMode
    target: ArchiveTarget
    relative_folder: Path
    bootstrap: bool = False

    @property
    def destination(self) -> Path:
        if self.relative_folder == Path("."):
            return self.target.version_path
        return self.target.version_path / self.relative_folder


def compute_placement(
    index: ProjectIndex,
    action: ArchiveAction,
    current: Coordinate | None,
    state: WorkflowState,
    result: str,
) -> ArchivePlacement:
    auditor_advances = (
        state.active_agent == Agent.AUDITOR and result in ("Pass", "Fail")
    )
    if auditor_advances:
        return ArchivePlacement(
            PlacementMode.CREATE,
            compute_target(index, action, current),
            Path("."),
        )

    existing = current_target(index, current)
    if existing is None:
        if action != ArchiveAction.CONTINUE:
            raise ValueError(
                "The first version is a fixed bootstrap; use Continue to create it"
            )
        return ArchivePlacement(
            PlacementMode.CREATE,
            compute_target(index, ArchiveAction.CONTINUE, current),
            Path("."),
            bootstrap=True,
        )

    if action != ArchiveAction.CONTINUE:
        raise ValueError(
            "Only an Auditor Pass or Fail may create a new branch or phase"
        )

    folder = Path(".")
    if state.active_agent == Agent.GUARDIAN and result == "Fail":
        if state.guardian_subject == Agent.OPERATOR:
            folder = Path("operator-fails")
        elif state.guardian_subject == Agent.AUDITOR:
            folder = Path("audit-fails")
        else:
            raise ValueError("Guardian has no submission subject for this failure")
    return ArchivePlacement(PlacementMode.APPEND, existing, folder)

