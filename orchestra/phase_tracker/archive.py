from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .archive_files import (
    copy_path,
    inventory,
    sha256_file,
    validate_sources,
)
from .archive_policy import ArchivePlacement, PlacementMode, compute_placement
from .archive_records import append_event, build_manifest
from .discovery import scan_project
from .domain import (
    ArchiveAction,
    ArchiveReceipt,
    ArchiveTarget,
    Coordinate,
    Transition,
    WorkflowState,
)
from .state_store import StateStore
from .workflow import advance


class ArchiveError(RuntimeError):
    pass


class ArchiveStateError(ArchiveError):
    def __init__(self, destination: Path, message: str):
        super().__init__(message)
        self.destination = destination


class ArchiveService:
    def record(
        self,
        project_root: Path,
        action: ArchiveAction,
        current: Coordinate | None,
        state: WorkflowState,
        result: str,
        artifacts: Iterable[Path],
        response: str,
        note: str = "",
    ) -> ArchiveReceipt:
        root = project_root.expanduser().resolve()
        if not root.is_dir():
            raise ArchiveError("Choose an existing project root")
        try:
            sources = validate_sources(root, artifacts)
            transition = advance(state, result)
            placement = compute_placement(
                scan_project(root), action, current, state, result
            )
        except ValueError as error:
            raise ArchiveError(str(error)) from error
        if not sources and not response.strip():
            raise ArchiveError("Add at least one artifact or paste a response")
        if placement.mode == PlacementMode.CREATE and placement.target.version_path.exists():
            raise ArchiveError(
                f"Destination already exists: {placement.target.version_path}"
            )
        for source in sources:
            if source.is_dir() and placement.destination.is_relative_to(source):
                raise ArchiveError(
                    f"A directory cannot be archived into its own descendant: {source}"
                )

        event_id = uuid.uuid4().hex
        moment = datetime.now(timezone.utc).astimezone()
        timestamp = moment.isoformat(timespec="seconds")
        file_stamp = moment.strftime("%Y%m%dT%H%M%S")
        if placement.mode == PlacementMode.CREATE:
            return self._record_create(
                root, placement, state, transition, sources, response, note,
                event_id, timestamp,
            )
        return self._record_append(
            root, placement, state, transition, sources, response, note,
            event_id, timestamp, file_stamp,
        )

    def _record_create(
        self,
        root: Path,
        placement: ArchivePlacement,
        state: WorkflowState,
        transition: Transition,
        sources: list[Path],
        response: str,
        note: str,
        event_id: str,
        timestamp: str,
    ) -> ArchiveReceipt:
        target = placement.target
        staging_root, staged_version = self._make_staging(target, event_id)
        store = StateStore(root)
        committed = False
        state_prepared = False
        try:
            staged = self._stage_inputs(
                staged_version, staged_version, target.coordinate, state,
                sources, response,
            )
            rows = self._inventory_rows(staged, staged_version, Path("."))
            manifest_name = f"{target.coordinate.version_name}-archive.json"
            manifest_relative = (
                target.coordinate.relative_path() / manifest_name
            ).as_posix()
            next_state = replace(
                transition.next_state,
                last_coordinate=target.coordinate,
                last_event_id=event_id,
                last_manifest=manifest_relative,
            )
            manifest = build_manifest(
                placement, state, transition, next_state, event_id, timestamp,
                note, rows,
            )
            (staged_version / manifest_name).write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            store.prepare(next_state)
            state_prepared = True
            self._commit_staging(target, staging_root)
            committed = True
            store.commit_prepared()
            state_prepared = False
        except Exception as error:
            if not committed and staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)
            if not committed and state_prepared:
                store.discard_prepared()
            if committed:
                raise ArchiveStateError(
                    target.version_path,
                    "The archive was created, but tracker metadata could not be "
                    "finalized. Reopening the project will recover it from the manifest.",
                ) from error
            raise
        warning = append_event(
            store, placement, state, transition, event_id, timestamp,
        )
        return ArchiveReceipt(
            event_id, target.version_path, target.coordinate, next_state,
            transition.handoff, len(sources), True, warning,
        )

    def _record_append(
        self,
        root: Path,
        placement: ArchivePlacement,
        state: WorkflowState,
        transition: Transition,
        sources: list[Path],
        response: str,
        note: str,
        event_id: str,
        timestamp: str,
        file_stamp: str,
    ) -> ArchiveReceipt:
        target_dir = placement.destination
        target_dir.mkdir(parents=True, exist_ok=True)
        store = StateStore(root)
        store.tracker_dir.mkdir(parents=True, exist_ok=True)
        staging = store.tracker_dir / f".staging-{event_id}"
        staging.mkdir()
        moved: list[tuple[Path, Path]] = []
        committed = False
        state_prepared = False
        manifest_name = (
            f"{placement.target.coordinate.version_name}-event-"
            f"{file_stamp}-{event_id[:8]}-archive.json"
        )
        manifest_final = target_dir / manifest_name
        try:
            staged = self._stage_inputs(
                staging, target_dir, placement.target.coordinate, state,
                sources, response,
            )
            rows = self._inventory_rows(
                staged, staging, placement.relative_folder
            )
            manifest_relative = manifest_final.relative_to(root).as_posix()
            next_state = replace(
                transition.next_state,
                last_coordinate=placement.target.coordinate,
                last_event_id=event_id,
                last_manifest=manifest_relative,
            )
            manifest = build_manifest(
                placement, state, transition, next_state, event_id, timestamp,
                note, rows,
            )
            manifest_staged = staging / manifest_name
            manifest_staged.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            store.prepare(next_state)
            state_prepared = True
            for staged_path in staged:
                final_path = target_dir / staged_path.name
                os.replace(staged_path, final_path)
                moved.append((final_path, staged_path))
            os.replace(manifest_staged, manifest_final)
            committed = True
            store.commit_prepared()
            state_prepared = False
            staging.rmdir()
        except Exception as error:
            if not committed:
                if manifest_final.exists():
                    os.replace(manifest_final, staging / manifest_name)
                for final_path, staged_path in reversed(moved):
                    if final_path.exists() or final_path.is_symlink():
                        os.replace(final_path, staged_path)
                if state_prepared:
                    store.discard_prepared()
                shutil.rmtree(staging, ignore_errors=True)
            if committed:
                raise ArchiveStateError(
                    target_dir,
                    "The return was recorded, but tracker metadata could not be "
                    "finalized. Reopening the project will recover it from the manifest.",
                ) from error
            raise
        warning = append_event(
            store, placement, state, transition, event_id, timestamp,
        )
        return ArchiveReceipt(
            event_id, target_dir, placement.target.coordinate, next_state,
            transition.handoff, len(sources), False, warning,
        )

    def _stage_inputs(
        self,
        staging: Path,
        collision_dir: Path,
        coordinate: Coordinate,
        state: WorkflowState,
        sources: list[Path],
        response: str,
    ) -> list[Path]:
        staged: list[Path] = []
        for source in sources:
            destination = self._available_across(
                staging, collision_dir, source.name
            )
            copy_path(source, destination)
            staged.append(destination)
        if response.strip():
            name = (
                f"{coordinate.version_name}-"
                f"{state.active_agent.value.lower()}-response.md"
            )
            destination = self._available_across(staging, collision_dir, name)
            destination.write_text(response.rstrip() + "\n", encoding="utf-8")
            staged.append(destination)
        return staged

    def _available_across(
        self, staging: Path, collision_dir: Path, name: str
    ) -> Path:
        original = Path(name)
        counter = 1
        while True:
            if counter == 1:
                candidate = original.name
            elif original.suffix:
                candidate = f"{original.stem}-{counter}{original.suffix}"
            else:
                candidate = f"{original.name}-{counter}"
            if not (staging / candidate).exists() and not (
                collision_dir / candidate
            ).exists():
                return staging / candidate
            counter += 1

    def _inventory_rows(
        self, staged: list[Path], base: Path, prefix: Path
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in staged:
            for row in inventory(path, base):
                if prefix != Path("."):
                    row["path"] = (prefix / row["path"]).as_posix()
                rows.append(row)
        return rows

    def _make_staging(
        self, target: ArchiveTarget, event_id: str
    ) -> tuple[Path, Path]:
        suffix = event_id[:10]
        coordinate = target.coordinate
        if not target.phase_path.exists():
            staging = (
                target.phase_path.parent
                / f".{target.phase_path.name}.staging-{suffix}"
            )
            version = staging / coordinate.branch_name / coordinate.version_name
        elif not target.branch_path.exists():
            staging = (
                target.branch_path.parent
                / f".{target.branch_path.name}.staging-{suffix}"
            )
            version = staging / coordinate.version_name
        else:
            staging = (
                target.version_path.parent
                / f".{target.version_path.name}.staging-{suffix}"
            )
            version = staging
        version.mkdir(parents=True, exist_ok=False)
        return staging, version

    def _commit_staging(self, target: ArchiveTarget, staging_root: Path) -> None:
        if not target.phase_path.exists():
            os.replace(staging_root, target.phase_path)
        elif not target.branch_path.exists():
            os.replace(staging_root, target.branch_path)
        else:
            os.replace(staging_root, target.version_path)
