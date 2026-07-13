from __future__ import annotations

from pathlib import Path
from typing import Any

from .archive_policy import ArchivePlacement, PlacementMode
from .domain import Transition, WorkflowState
from .state_store import StateStore


SCHEMA_VERSION = 2


def build_manifest(
    placement: ArchivePlacement,
    state: WorkflowState,
    transition: Transition,
    next_state: WorkflowState,
    event_id: str,
    timestamp: str,
    note: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    coordinate_authority = None
    if placement.bootstrap:
        coordinate_authority = "STRUCTURAL BOOTSTRAP"
    elif placement.mode == PlacementMode.CREATE:
        coordinate_authority = "AUDITOR RESULT"
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type(placement),
        "recorded_at": timestamp,
        "coordinate": placement.target.coordinate.to_dict(),
        "coordinate_authority": coordinate_authority,
        "archive_action": placement.target.action.value,
        "placement": placement.relative_folder.as_posix(),
        "source_agent": state.active_agent.value,
        "guardian_subject": (
            state.guardian_subject.value if state.guardian_subject else None
        ),
        "result": transition.result,
        "next_agent": next_state.active_agent.value,
        "next_guardian_subject": (
            next_state.guardian_subject.value
            if next_state.guardian_subject else None
        ),
        "project_status": next_state.status.value,
        "next_state": next_state.to_dict(),
        "handoff": transition.handoff,
        "operator_note": note.strip() or None,
        "files": rows,
    }


def append_event(
    store: StateStore,
    placement: ArchivePlacement,
    state: WorkflowState,
    transition: Transition,
    event_id: str,
    timestamp: str,
) -> str | None:
    try:
        store.append_event({
            "event_id": event_id,
            "event_type": event_type(placement),
            "recorded_at": timestamp,
            "coordinate": placement.target.coordinate.to_dict(),
            "archive_action": placement.target.action.value,
            "placement": placement.relative_folder.as_posix(),
            "source_agent": state.active_agent.value,
            "result": transition.result,
            "next_agent": transition.next_state.active_agent.value,
            "handoff": transition.handoff,
            "path": placement.destination.relative_to(
                store.project_root
            ).as_posix(),
        })
    except OSError:
        return (
            "The archive is complete, but the convenience event journal "
            "was not updated."
        )
    return None


def event_type(placement: ArchivePlacement) -> str:
    return (
        "coordinate_created"
        if placement.mode == PlacementMode.CREATE
        else "current_version_append"
    )

