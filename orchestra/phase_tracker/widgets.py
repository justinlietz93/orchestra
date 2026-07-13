from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .domain import Agent, ProjectStatus, WorkflowState
from .domain import ArchiveAction


class DropZone(QFrame):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setProperty("dragActive", False)
        self.setAcceptDrops(True)
        self.setMinimumHeight(150)

        layout = QVBoxLayout(self)
        heading = QLabel("DROP PACKAGES, FILES, OR FOLDERS HERE")
        heading.setObjectName("activeText")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail = QLabel("Original names and directory structure are preserved")
        detail.setObjectName("muted")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setMinimumHeight(60)

        controls = QHBoxLayout()
        add_files = QPushButton("Add files")
        add_folder = QPushButton("Add folder")
        remove = QPushButton("Remove selected")
        clear = QPushButton("Clear")
        add_files.clicked.connect(self._choose_files)
        add_folder.clicked.connect(self._choose_folder)
        remove.clicked.connect(self._remove_selected)
        clear.clicked.connect(self.clear)
        controls.addWidget(add_files)
        controls.addWidget(add_folder)
        controls.addStretch(1)
        controls.addWidget(remove)
        controls.addWidget(clear)

        layout.addWidget(heading)
        layout.addWidget(detail)
        layout.addWidget(self.list)
        layout.addLayout(controls)

    def paths(self) -> list[Path]:
        return [Path(self.list.item(index).data(Qt.ItemDataRole.UserRole)) for index in range(self.list.count())]

    def add_paths(self, paths: list[Path]) -> None:
        known = {str(path) for path in self.paths()}
        for path in paths:
            resolved = path.expanduser().resolve()
            if str(resolved) in known:
                continue
            self.list.addItem(str(resolved))
            item = self.list.item(self.list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, str(resolved))
            item.setToolTip(str(resolved))
            known.add(str(resolved))
        self.changed.emit()

    def clear(self) -> None:
        self.list.clear()
        self.changed.emit()

    def dragEnterEvent(self, event: QEvent) -> None:
        if event.mimeData().hasUrls():
            self._set_drag_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QEvent) -> None:
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event: QEvent) -> None:
        self._set_drag_active(False)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        self.add_paths(paths)
        event.acceptProposedAction()

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def _choose_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Add artifacts")
        self.add_paths([Path(name) for name in names])

    def _choose_folder(self) -> None:
        name = QFileDialog.getExistingDirectory(self, "Add artifact folder")
        if name:
            self.add_paths([Path(name)])

    def _remove_selected(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self.changed.emit()


class AgentCard(QFrame):
    def __init__(self, agent: Agent):
        super().__init__()
        self.agent = agent
        self.setObjectName("agentCard")
        self.setProperty("active", False)
        self.setMinimumWidth(150)
        layout = QVBoxLayout(self)
        self.name = QLabel(agent.value.upper())
        self.name.setObjectName("eyebrow")
        self.status = QLabel("Waiting")
        self.status.setWordWrap(True)
        layout.addWidget(self.name)
        layout.addWidget(self.status)

    def set_active(self, active: bool, status: str) -> None:
        self.setProperty("active", active)
        self.status.setText(status)
        self.status.setObjectName("activeText" if active else "muted")
        self.style().unpolish(self)
        self.style().polish(self)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)


class WorkflowPanel(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)

        heading = QHBoxLayout()
        title = QLabel("WORKFLOW POSITION")
        title.setObjectName("eyebrow")
        self.current = QLabel()
        self.current.setObjectName("activeText")
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(self.current)
        layout.addLayout(heading)

        cards = QHBoxLayout()
        self.agent_cards = {agent: AgentCard(agent) for agent in Agent}
        for index, agent in enumerate((Agent.OPERATOR, Agent.GUARDIAN, Agent.AUDITOR)):
            cards.addWidget(self.agent_cards[agent])
            if index < 2:
                arrow = QLabel("→")
                arrow.setObjectName("muted")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cards.addWidget(arrow)
        layout.addLayout(cards)

        self.handoff = QLabel()
        self.handoff.setWordWrap(True)
        self.handoff.setObjectName("muted")
        layout.addWidget(self.handoff)

    def update_state(self, state: WorkflowState, last_handoff: str = "") -> None:
        if state.status == ProjectStatus.COMPLETE:
            self.current.setText("PROJECT COMPLETE")
            for card in self.agent_cards.values():
                card.set_active(False, "Complete")
            self.handoff.setText("The project is closed. Reopen it from the Workflow menu if work resumes.")
            return

        self.current.setText(f"AWAITING {state.active_agent.value.upper()}")
        for agent, card in self.agent_cards.items():
            if agent == state.active_agent:
                if agent == Agent.GUARDIAN and state.guardian_subject:
                    status = f"Reviewing {state.guardian_subject.value}"
                elif agent == Agent.AUDITOR and state.auditor_revision:
                    status = "Revision after Guardian fail"
                else:
                    status = "Current response source"
                card.set_active(True, status)
            else:
                card.set_active(False, "Waiting")
        self.handoff.setText(last_handoff or f"Record the next {state.active_agent.value} response and artifacts.")


class ArchiveIntake(QFrame):
    archive_requested = Signal(object)
    paste_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)

        heading = QHBoxLayout()
        source_label = QLabel("RECORD AGENT RETURN")
        source_label.setObjectName("eyebrow")
        self.source_badge = QLabel("OPERATOR")
        self.source_badge.setObjectName("activeText")
        self.result_combo = QComboBox()
        heading.addWidget(source_label)
        heading.addStretch(1)
        heading.addWidget(QLabel("Source"))
        heading.addWidget(self.source_badge)
        heading.addSpacing(16)
        heading.addWidget(QLabel("Result"))
        heading.addWidget(self.result_combo)
        layout.addLayout(heading)

        self.drop_zone = DropZone()
        layout.addWidget(self.drop_zone)

        response_header = QHBoxLayout()
        response_label = QLabel("PASTED RESPONSE")
        response_label.setObjectName("eyebrow")
        paste = QPushButton("Paste clipboard")
        paste.clicked.connect(lambda: self.paste_requested.emit())
        response_header.addWidget(response_label)
        response_header.addStretch(1)
        response_header.addWidget(paste)
        layout.addLayout(response_header)

        self.response_edit = QPlainTextEdit()
        self.response_edit.setPlaceholderText("Paste the complete agent response here…")
        self.response_edit.setMinimumHeight(150)
        layout.addWidget(self.response_edit, 1)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Optional operator note for this handoff")
        layout.addWidget(self.note_edit)

        preview_label = QLabel("ARCHIVE DESTINATIONS")
        preview_label.setObjectName("eyebrow")
        layout.addWidget(preview_label)
        actions = QHBoxLayout()
        self.continue_button = QPushButton()
        self.continue_button.setObjectName("primary")
        self.continue_button.clicked.connect(
            lambda: self.archive_requested.emit(ArchiveAction.CONTINUE)
        )
        self.branch_button = QPushButton()
        self.branch_button.setObjectName("branch")
        self.branch_button.clicked.connect(
            lambda: self.archive_requested.emit(ArchiveAction.NEW_BRANCH)
        )
        self.phase_button = QPushButton()
        self.phase_button.setObjectName("phase")
        self.phase_button.clicked.connect(
            lambda: self.archive_requested.emit(ArchiveAction.NEW_PHASE)
        )
        actions.addWidget(self.continue_button, 1)
        actions.addWidget(self.branch_button, 1)
        actions.addWidget(self.phase_button, 1)
        layout.addLayout(actions)

    def clear_return(self) -> None:
        self.drop_zone.clear()
        self.response_edit.clear()
        self.note_edit.clear()
