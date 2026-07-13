from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .domain import WorkflowState


TRACKER_DIR = ".project-handoff"
STATE_FILE = "state.json"
PENDING_STATE_FILE = "state.pending.json"
EVENTS_FILE = "events.jsonl"


class StateStore:
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.tracker_dir = self.project_root / TRACKER_DIR
        self.state_path = self.tracker_dir / STATE_FILE
        self.pending_state_path = self.tracker_dir / PENDING_STATE_FILE
        self.events_path = self.tracker_dir / EVENTS_FILE

    def load(self) -> WorkflowState:
        self._recover_pending()
        if not self.state_path.exists():
            return WorkflowState()
        with self.state_path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return WorkflowState.from_dict(value)

    def save(self, state: WorkflowState) -> None:
        self.prepare(state)
        self.commit_prepared()

    def prepare(self, state: WorkflowState) -> None:
        self.tracker_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.pending_state_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(state.to_dict(), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.pending_state_path)

    def commit_prepared(self) -> None:
        os.replace(self.pending_state_path, self.state_path)

    def discard_prepared(self) -> None:
        self.pending_state_path.unlink(missing_ok=True)

    def append_event(self, event: dict[str, Any]) -> None:
        self.tracker_dir.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            json.dump(event, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def read_events(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows[-limit:]

    def _recover_pending(self) -> None:
        if not self.pending_state_path.exists():
            return
        try:
            with self.pending_state_path.open("r", encoding="utf-8") as handle:
                pending = WorkflowState.from_dict(json.load(handle))
            coordinate = pending.last_coordinate
            if not coordinate or not pending.last_event_id:
                self.discard_prepared()
                return
            if pending.last_manifest:
                manifest = self.project_root / pending.last_manifest
            else:
                destination = self.project_root / coordinate.relative_path()
                manifest = destination / f"{coordinate.version_name}-archive.json"
            if not manifest.exists():
                self.discard_prepared()
                return
            with manifest.open("r", encoding="utf-8") as handle:
                event_id = json.load(handle).get("event_id")
            if event_id == pending.last_event_id:
                self.commit_prepared()
            else:
                self.discard_prepared()
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            self.discard_prepared()
