from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(path: Path, base: Path) -> list[dict[str, Any]]:
    if path.is_symlink():
        return [{
            "path": path.relative_to(base).as_posix(),
            "type": "symlink",
            "target": os.readlink(path),
        }]
    if path.is_file():
        return [{
            "path": path.relative_to(base).as_posix(),
            "type": "file",
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }]
    rows: list[dict[str, Any]] = []
    for child in sorted(path.rglob("*")):
        if child.is_symlink():
            rows.append({
                "path": child.relative_to(base).as_posix(),
                "type": "symlink",
                "target": os.readlink(child),
            })
        elif child.is_file():
            rows.append({
                "path": child.relative_to(base).as_posix(),
                "type": "file",
                "size": child.stat().st_size,
                "sha256": sha256_file(child),
            })
    return rows


def validate_sources(root: Path, artifacts: Iterable[Path]) -> list[Path]:
    sources: list[Path] = []
    seen: set[Path] = set()
    for raw in artifacts:
        source = raw.expanduser().resolve()
        if source in seen:
            continue
        if not source.exists() and not source.is_symlink():
            raise ValueError(f"Artifact does not exist: {source}")
        if source == root or source in root.parents:
            raise ValueError(
                "The project root or one of its parents cannot be an artifact"
            )
        seen.add(source)
        sources.append(source)
    return sources


def available_destination(directory: Path, name: str) -> Path:
    candidate = directory / name
    counter = 2
    while candidate.exists() or candidate.is_symlink():
        path = Path(name)
        if path.suffix:
            candidate = directory / f"{path.stem}-{counter}{path.suffix}"
        else:
            candidate = directory / f"{name}-{counter}"
        counter += 1
    return candidate


def copy_path(source: Path, destination: Path) -> None:
    if source.is_symlink():
        destination.symlink_to(
            os.readlink(source),
            target_is_directory=source.is_dir(),
        )
    elif source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination)

