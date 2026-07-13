from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .archive_policy import PlacementMode, compute_placement
from .discovery import ProjectIndex
from .domain import ArchiveAction, Coordinate, ProjectStatus, WorkflowState


@dataclass(frozen=True)
class ArchivePreview:
    text: str
    tooltip: str
    enabled: bool


def build_previews(
    root: Path,
    index: ProjectIndex,
    current: Coordinate | None,
    state: WorkflowState,
    result: str,
) -> dict[ArchiveAction, ArchivePreview]:
    previews: dict[ArchiveAction, ArchivePreview] = {}
    headings = {
        ArchiveAction.CONTINUE: "CONTINUE",
        ArchiveAction.NEW_BRANCH: "NEW BRANCH",
        ArchiveAction.NEW_PHASE: "NEW PHASE",
    }
    for action, heading in headings.items():
        try:
            placement = compute_placement(index, action, current, state, result)
            if placement.bootstrap:
                action_text = "INITIALIZE FIRST VERSION"
            elif placement.mode == PlacementMode.APPEND:
                action_text = "RECORD IN CURRENT VERSION"
            elif action == ArchiveAction.CONTINUE:
                action_text = "ADVANCE VERSION"
            else:
                action_text = heading
            relative = placement.destination.relative_to(root).as_posix()
            previews[action] = ArchivePreview(
                f"{action_text}\n{relative}",
                str(placement.destination),
                state.status == ProjectStatus.IN_PROGRESS,
            )
        except ValueError as error:
            previews[action] = ArchivePreview(
                f"{heading}\nAUDITOR PASS/FAIL ONLY",
                str(error),
                False,
            )
    return previews

