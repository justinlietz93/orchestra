from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .domain import ArchiveAction, ArchiveTarget, Coordinate


PHASE_PATTERNS = (
    re.compile(r"^p(?P<phase>\d+)$", re.IGNORECASE),
    re.compile(
        r"^phase[-_ ]?(?P<phase>\d+)(?:$|[-_ ].*)",
        re.IGNORECASE,
    ),
)
BRANCH_PATTERN = re.compile(r"^p(?P<phase>\d+)-b(?P<branch>\d+)$")
VERSION_PATTERN = re.compile(
    r"^p(?P<phase>\d+)-b(?P<branch>\d+)-v(?P<version>\d+)$"
)


@dataclass
class BranchEntry:
    number: int
    path: Path
    versions: list[int] = field(default_factory=list)

    @property
    def latest_version(self) -> int:
        return max(self.versions, default=0)


@dataclass
class PhaseEntry:
    number: int
    path: Path
    branches: dict[int, BranchEntry] = field(default_factory=dict)

    @property
    def latest_branch(self) -> int:
        return max(self.branches, default=0)


@dataclass
class ProjectIndex:
    root: Path
    phases: dict[int, PhaseEntry] = field(default_factory=dict)
    duplicate_phases: dict[int, list[Path]] = field(default_factory=dict)

    @property
    def latest_phase(self) -> int:
        return max(self.phases, default=0)

    def latest_coordinate(self) -> Coordinate | None:
        if not self.phases:
            return None
        phase = self.phases[self.latest_phase]
        if not phase.branches:
            return Coordinate(phase.number, 0, 0, phase.path.name)
        branch = phase.branches[phase.latest_branch]
        return Coordinate(
            phase.number,
            branch.number,
            branch.latest_version,
            phase.path.name,
        )

    def coordinate_for(self, phase_number: int, branch_number: int) -> Coordinate:
        phase = self.phases[phase_number]
        branch = phase.branches[branch_number]
        return Coordinate(
            phase.number,
            branch.number,
            branch.latest_version,
            phase.path.name,
        )


def phase_number_from_name(name: str) -> int | None:
    for pattern in PHASE_PATTERNS:
        match = pattern.match(name)
        if match:
            return int(match.group("phase"))
    return None


def scan_project(root: Path) -> ProjectIndex:
    root = root.expanduser().resolve()
    index = ProjectIndex(root=root)
    if not root.is_dir():
        return index

    candidates: dict[int, list[Path]] = {}
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        phase_number = phase_number_from_name(child.name)
        if phase_number is not None:
            candidates.setdefault(phase_number, []).append(child)

    for number, paths in candidates.items():
        ordered = sorted(paths, key=lambda path: (not path.name.lower() == f"p{number}", path.name))
        selected = ordered[0]
        if len(ordered) > 1:
            index.duplicate_phases[number] = ordered
        phase = PhaseEntry(number=number, path=selected)

        for branch_path in selected.iterdir():
            if not branch_path.is_dir():
                continue
            branch_match = BRANCH_PATTERN.fullmatch(branch_path.name)
            if not branch_match or int(branch_match.group("phase")) != number:
                continue
            branch_number = int(branch_match.group("branch"))
            branch = BranchEntry(number=branch_number, path=branch_path)
            for version_path in branch_path.iterdir():
                if not version_path.is_dir():
                    continue
                version_match = VERSION_PATTERN.fullmatch(version_path.name)
                if not version_match:
                    continue
                if (
                    int(version_match.group("phase")) == number
                    and int(version_match.group("branch")) == branch_number
                ):
                    branch.versions.append(int(version_match.group("version")))
            branch.versions.sort()
            phase.branches[branch_number] = branch
        index.phases[number] = phase
    return index


def compute_target(
    index: ProjectIndex,
    action: ArchiveAction,
    current: Coordinate | None,
) -> ArchiveTarget:
    if index.duplicate_phases:
        details = ", ".join(
            f"p{number}: {[path.name for path in paths]}"
            for number, paths in sorted(index.duplicate_phases.items())
        )
        raise ValueError(f"Ambiguous phase directories: {details}")

    if not index.phases:
        return _target(index.root, action, 1, "p1", 1, 1)

    if action == ArchiveAction.NEW_PHASE:
        phase = index.latest_phase + 1
        return _target(index.root, action, phase, f"p{phase}", 1, 1)

    selected = current or index.latest_coordinate()
    if selected is None or selected.phase not in index.phases:
        raise ValueError("The selected phase no longer exists")
    phase_entry = index.phases[selected.phase]

    if action == ArchiveAction.NEW_BRANCH:
        branch = phase_entry.latest_branch + 1
        return _target(
            index.root,
            action,
            phase_entry.number,
            phase_entry.path.name,
            branch,
            1,
        )

    if selected.branch not in phase_entry.branches:
        if phase_entry.branches:
            raise ValueError("Select an existing branch before continuing")
        branch = 1
        version = 1
    else:
        branch_entry = phase_entry.branches[selected.branch]
        branch = branch_entry.number
        version = branch_entry.latest_version + 1
    return _target(
        index.root,
        action,
        phase_entry.number,
        phase_entry.path.name,
        branch,
        version,
    )


def current_target(
    index: ProjectIndex,
    current: Coordinate | None,
) -> ArchiveTarget | None:
    selected = current or index.latest_coordinate()
    if not selected or selected.version < 1:
        return None
    phase = index.phases.get(selected.phase)
    if not phase:
        return None
    branch = phase.branches.get(selected.branch)
    if not branch or selected.version not in branch.versions:
        return None
    return _target(
        index.root,
        ArchiveAction.CONTINUE,
        selected.phase,
        phase.path.name,
        selected.branch,
        selected.version,
    )


def _target(
    root: Path,
    action: ArchiveAction,
    phase: int,
    phase_dir: str,
    branch: int,
    version: int,
) -> ArchiveTarget:
    coordinate = Coordinate(phase, branch, version, phase_dir)
    phase_path = root / phase_dir
    branch_path = phase_path / coordinate.branch_name
    version_path = branch_path / coordinate.version_name
    return ArchiveTarget(
        coordinate=coordinate,
        action=action,
        phase_path=phase_path,
        branch_path=branch_path,
        version_path=version_path,
    )
