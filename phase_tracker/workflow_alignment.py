from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .domain import WorkflowState
from .state_store import StateStore
from .workflow import align_position, describe_position


@dataclass(frozen=True)
class AlignmentReceipt:
    state: WorkflowState
    handoff: str
    warning: str | None = None


def record_alignment(
    project_root: Path,
    current_state: WorkflowState,
    position: str,
) -> AlignmentReceipt:
    previous_position = describe_position(current_state)
    next_state = align_position(current_state, position)
    event_id = uuid.uuid4().hex
    recorded_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    handoff = (
        f"Workflow position manually aligned: {previous_position} → {position}"
    )
    store = StateStore(project_root)
    store.save(next_state)

    warning = None
    try:
        store.append_event(
            {
                "event_id": event_id,
                "event_type": "manual_workflow_alignment",
                "recorded_at": recorded_at,
                "previous_position": previous_position,
                "next_position": position,
                "handoff": handoff,
                "path": (
                    next_state.last_coordinate.relative_path().as_posix()
                    if next_state.last_coordinate
                    else None
                ),
            }
        )
    except OSError:
        warning = "The position was saved, but the convenience event journal was not updated."
    return AlignmentReceipt(next_state, handoff, warning)

