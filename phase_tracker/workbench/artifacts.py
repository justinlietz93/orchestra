from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path
from typing import Iterable

from ..archive_files import sha256_file
from ..content_extractors import extract_searchable_text
from .domain import RunPolicy, SourceSnapshot
from .store import WorkbenchStore


class ContentAddressedStore:
    def __init__(self, store: WorkbenchStore):
        self.store = store

    def put_file(self, source: Path, expected_sha256: str) -> str:
        target = self._target(expected_sha256)
        if target.exists():
            if sha256_file(target) != expected_sha256:
                raise ValueError(f"Corrupt content object: {target}")
            return target.relative_to(self.store.project_root).as_posix()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(source, temporary)
            self._sync_file(temporary)
            if sha256_file(temporary) != expected_sha256:
                raise ValueError(f"Source changed while snapshotting: {source}")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target.relative_to(self.store.project_root).as_posix()

    def put_bytes(self, content: bytes) -> tuple[str, str]:
        digest = hashlib.sha256(content).hexdigest()
        target = self._target(digest)
        if target.exists():
            if sha256_file(target) != digest:
                raise ValueError(f"Corrupt content object: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(
                f".{target.name}.{uuid.uuid4().hex}.tmp"
            )
            try:
                with temporary.open("xb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        relative = target.relative_to(self.store.project_root).as_posix()
        return digest, relative

    def _target(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Content digest must be lowercase SHA-256")
        return self.store.objects_dir / digest[:2] / digest

    @staticmethod
    def _sync_file(path: Path) -> None:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())


class ArtifactSnapshotService:
    def __init__(self, project_root: Path, policy: RunPolicy | None = None):
        self.root = project_root.expanduser().resolve()
        self.policy = policy or RunPolicy()
        self.store = WorkbenchStore(self.root)
        self.objects = ContentAddressedStore(self.store)

    def snapshot_selected(
        self, selected_paths: Iterable[Path]
    ) -> tuple[SourceSnapshot, ...]:
        resolved = self._validated_paths(selected_paths)
        if not resolved:
            raise ValueError("Select at least one project artifact")
        if len(resolved) > self.policy.max_files:
            raise ValueError(
                f"This run permits at most {self.policy.max_files} selected files"
            )
        snapshots: list[SourceSnapshot] = []
        for path in resolved:
            digest_before = sha256_file(path)
            extraction_note = None
            try:
                extracted = extract_searchable_text(path)
            except Exception as error:
                extracted = ""
                extraction_note = f"Text extraction unavailable: {type(error).__name__}"
            digest_after = sha256_file(path)
            if digest_before != digest_after:
                raise ValueError(f"Artifact changed during the run: {path}")
            object_path = self.objects.put_file(path, digest_before)
            relative = path.relative_to(self.root).as_posix()
            snapshots.append(SourceSnapshot(
                artifact_id=f"src_{digest_before[:24]}",
                source_path=relative,
                sha256=digest_before,
                size=path.stat().st_size,
                object_path=object_path,
                extracted_text=extracted,
                extraction_note=extraction_note,
            ))
        return tuple(snapshots)

    def _validated_paths(self, selected_paths: Iterable[Path]) -> list[Path]:
        unique: dict[str, Path] = {}
        for candidate in selected_paths:
            path = candidate.expanduser()
            if not path.is_absolute():
                path = self.root / path
            absolute = path.absolute()
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(self.root)
            except ValueError as error:
                raise ValueError(
                    f"Research artifacts must be inside the project root: {candidate}"
                ) from error
            if absolute != resolved:
                raise ValueError(f"Symlinked research paths are not allowed: {candidate}")
            if not resolved.is_file():
                raise ValueError(f"Select regular project files only: {candidate}")
            if relative.parts and relative.parts[0] == ".project-handoff":
                raise ValueError("Internal Orchestra control files cannot be research inputs")
            unique[relative.as_posix()] = resolved
        return [unique[key] for key in sorted(unique)]


class InternalCorpusConnector:
    def __init__(self, snapshot_service: ArtifactSnapshotService):
        self.snapshot_service = snapshot_service

    def collect(self, selected_paths: Iterable[Path]) -> tuple[SourceSnapshot, ...]:
        return self.snapshot_service.snapshot_selected(selected_paths)


class ResearchSummaryService:
    def __init__(self, policy: RunPolicy | None = None):
        self.policy = policy or RunPolicy()

    def render(
        self,
        objective: str,
        graph_node_path: str,
        sources: tuple[SourceSnapshot, ...],
    ) -> str:
        lines = [
            "# User Research Workbench Summary",
            "",
            "> **USER RESEARCH · CREATED · NOT PROVIDED**",
            "",
            "Generated by the user Research Workbench.",
            "",
            "Not provided to any agent unless an exposure event says otherwise.",
            "",
            "## Research objective",
            "",
            objective.strip(),
            "",
            "## Graph launch point",
            "",
            f"`{graph_node_path}`",
            "",
            "## Explicitly selected evidence",
            "",
        ]
        remaining = self.policy.max_summary_source_chars
        for source in sources:
            lines.extend([
                f"### `{source.source_path}`",
                "",
                f"- SHA-256: `{source.sha256}`",
                f"- Size: {source.size} bytes",
                "- Snapshot: exact project bytes",
                "",
            ])
            excerpt = " ".join(source.extracted_text.split())
            excerpt = excerpt[: self.policy.max_excerpt_chars_per_file]
            excerpt = excerpt[:remaining]
            if excerpt:
                lines.extend(["Excerpt:", "", excerpt, ""])
                remaining -= len(excerpt)
            else:
                lines.extend([source.extraction_note or "No text was extracted.", ""])
        lines.extend([
            "## Limitations",
            "",
            "This internal-only run inventories and excerpts only the files explicitly "
            "selected by the user. It performs no external research, agent delivery, "
            "claim promotion, audit, adoption, or publication step.",
            "",
        ])
        return "\n".join(lines)
