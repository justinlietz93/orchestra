from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from .archive import ArchiveError, ArchiveService, ArchiveStateError
from .archive_preview import build_previews
from .discovery import ProjectIndex, scan_project
from .domain import ArchiveAction, Coordinate, ProjectStatus, WorkflowState
from .project_navigator import ProjectNavigator
from .search_panel import SearchPanel
from .state_store import StateStore
from .theme import APP_STYLE
from .widgets import ArchiveIntake, WorkflowPanel
from .workflow import (
    WORKFLOW_POSITIONS,
    available_results,
    describe_position,
)
from .workflow_alignment import record_alignment
class MainWindow(QMainWindow):
    def __init__(self, initial_root: Path | None = None):
        super().__init__()
        self.setWindowTitle("Orchestra")
        self.resize(1540, 940)
        self.setMinimumSize(1120, 720)
        self.setStyleSheet(APP_STYLE)
        self.root: Path | None = None
        self.index: ProjectIndex | None = None
        self.state = WorkflowState()
        self.current_coordinate: Coordinate | None = None
        self.last_handoff = ""
        self.archive_service = ArchiveService()
        self._build_menu()
        self._build_ui()
        if initial_root and initial_root.is_dir():
            self.open_project(initial_root)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Project")
        choose = QAction("Open project root…", self)
        choose.setShortcut("Ctrl+O")
        choose.triggered.connect(self.choose_root)
        refresh = QAction("Refresh project", self)
        refresh.setShortcut("F5")
        refresh.triggered.connect(self.refresh_project)
        file_menu.addAction(choose)
        file_menu.addAction(refresh)
        workflow_menu = self.menuBar().addMenu("Workflow")
        reopen = QAction("Reopen completed project", self)
        reopen.triggered.connect(self.reopen_project)
        set_position = QAction("Set workflow position…", self)
        set_position.setShortcut("Ctrl+Shift+W")
        set_position.triggered.connect(self.set_workflow_position)
        workflow_menu.addAction(reopen)
        workflow_menu.addAction(set_position)

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(10)
        header = QHBoxLayout()
        identity = QVBoxLayout()
        eyebrow = QLabel("THREE-AGENT PROVENANCE CONTROL")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Orchestra")
        title.setObjectName("title")
        identity.addWidget(eyebrow)
        identity.addWidget(title)
        header.addLayout(identity)
        header.addStretch(1)
        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("Choose or enter a project root")
        self.root_edit.setMinimumWidth(480)
        self.root_edit.returnPressed.connect(self._open_typed_root)
        root_button = QPushButton("Switch root")
        root_button.clicked.connect(self.choose_root)
        open_button = QPushButton("Open")
        open_button.setObjectName("primary")
        open_button.clicked.connect(self._open_typed_root)
        header.addWidget(self.root_edit)
        header.addWidget(root_button)
        header.addWidget(open_button)
        outer.addLayout(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.navigator = ProjectNavigator()
        self.navigator.open_requested.connect(lambda path: self._open_path(Path(path)))
        splitter.addWidget(self.navigator)
        splitter.addWidget(self._build_work_area())
        self.search_panel = SearchPanel()
        self.search_panel.reveal_requested.connect(self.reveal_path)
        self.search_panel.open_requested.connect(self.open_relative_path)
        splitter.addWidget(self.search_panel)
        splitter.setSizes([330, 740, 430])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        outer.addWidget(splitter, 1)
        self.setCentralWidget(central)

    def _build_work_area(self) -> QWidget:
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        location = QFrame()
        location.setObjectName("panel")
        location_layout = QHBoxLayout(location)
        label = QLabel("ACTIVE LINE")
        label.setObjectName("eyebrow")
        self.phase_combo = QComboBox()
        self.phase_combo.currentIndexChanged.connect(self._phase_changed)
        self.branch_combo = QComboBox()
        self.branch_combo.currentIndexChanged.connect(self._branch_changed)
        self.version_label = QLabel("No archived interactions")
        self.version_label.setObjectName("muted")
        location_layout.addWidget(label)
        location_layout.addWidget(QLabel("Phase"))
        location_layout.addWidget(self.phase_combo)
        location_layout.addWidget(QLabel("Branch"))
        location_layout.addWidget(self.branch_combo)
        location_layout.addWidget(self.version_label)
        location_layout.addStretch(1)
        layout.addWidget(location)

        self.workflow_panel = WorkflowPanel()
        layout.addWidget(self.workflow_panel)

        self.intake = ArchiveIntake()
        self.intake.archive_requested.connect(self.archive)
        self.intake.paste_requested.connect(self.paste_response)
        self.source_badge = self.intake.source_badge
        self.result_combo = self.intake.result_combo
        self.drop_zone = self.intake.drop_zone
        self.response_edit = self.intake.response_edit
        self.note_edit = self.intake.note_edit
        self.continue_button = self.intake.continue_button
        self.branch_button = self.intake.branch_button
        self.phase_button = self.intake.phase_button
        self.result_combo.currentTextChanged.connect(
            lambda _value: self._update_previews()
        )
        layout.addWidget(self.intake, 1)
        return area

    def choose_root(self) -> None:
        start = str(self.root or Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Choose project root", start)
        if selected:
            self.open_project(Path(selected))

    def _open_typed_root(self) -> None:
        value = self.root_edit.text().strip()
        if value:
            self.open_project(Path(value).expanduser())

    def open_project(self, root: Path) -> None:
        root = root.expanduser().resolve()
        if not root.is_dir():
            QMessageBox.warning(self, "Project root", f"Directory does not exist:\n{root}")
            return
        self.root = root
        self.root_edit.setText(str(root))
        try:
            self.state = StateStore(root).load()
        except Exception as error:
            QMessageBox.warning(self, "Tracker state", f"Could not load tracker state:\n{error}")
            self.state = WorkflowState()
        self.last_handoff = self._last_handoff()
        self.refresh_project()
        self.search_panel.set_root(root)

    def refresh_project(self) -> None:
        if not self.root:
            return
        self.navigator.refresh(self.root)
        self.index = scan_project(self.root)
        self._populate_coordinates()
        self._update_workflow()
        self._update_previews()

    def _populate_coordinates(self) -> None:
        assert self.index is not None
        preferred = self.state.last_coordinate or self.index.latest_coordinate()
        self.phase_combo.blockSignals(True)
        self.phase_combo.clear()
        for number, phase in sorted(self.index.phases.items()):
            self.phase_combo.addItem(f"p{number} · {phase.path.name}", number)
        if preferred and preferred.phase in self.index.phases:
            position = self.phase_combo.findData(preferred.phase)
            self.phase_combo.setCurrentIndex(position)
        self.phase_combo.blockSignals(False)
        self._populate_branches(preferred.branch if preferred else None)

    def _populate_branches(self, preferred_branch: int | None = None) -> None:
        if not self.index:
            return
        phase_number = self.phase_combo.currentData()
        self.branch_combo.blockSignals(True)
        self.branch_combo.clear()
        if phase_number in self.index.phases:
            phase = self.index.phases[phase_number]
            for number in sorted(phase.branches):
                self.branch_combo.addItem(f"p{phase_number}-b{number}", number)
            if preferred_branch in phase.branches:
                self.branch_combo.setCurrentIndex(self.branch_combo.findData(preferred_branch))
            elif self.branch_combo.count():
                self.branch_combo.setCurrentIndex(self.branch_combo.count() - 1)
        self.branch_combo.blockSignals(False)
        self._set_current_coordinate()

    def _phase_changed(self) -> None:
        self._populate_branches()
        self._update_previews()

    def _branch_changed(self) -> None:
        self._set_current_coordinate()
        self._update_previews()

    def _set_current_coordinate(self) -> None:
        if not self.index:
            self.current_coordinate = None
            return
        phase = self.phase_combo.currentData()
        branch = self.branch_combo.currentData()
        if phase in self.index.phases and branch in self.index.phases[phase].branches:
            self.current_coordinate = self.index.coordinate_for(phase, branch)
            version = self.current_coordinate.version
            self.version_label.setText(
                f"Latest: {self.current_coordinate.version_name}" if version else "No versions"
            )
        else:
            self.current_coordinate = self.index.latest_coordinate()
            self.version_label.setText("No archived interactions")

    def _update_workflow(self) -> None:
        self.workflow_panel.update_state(self.state, self.last_handoff)
        self.source_badge.setText(self.state.active_agent.value.upper())
        self.result_combo.clear()
        self.result_combo.addItems(available_results(self.state))
        enabled = self.state.status == ProjectStatus.IN_PROGRESS and self.root is not None
        self.result_combo.setEnabled(enabled)
        for button in (self.continue_button, self.branch_button, self.phase_button):
            button.setEnabled(enabled)

    def _update_previews(self) -> None:
        if not self.root or not self.index:
            self.continue_button.setText("Continue")
            self.branch_button.setText("New branch")
            self.phase_button.setText("New phase")
            return
        buttons = {
            ArchiveAction.CONTINUE: self.continue_button,
            ArchiveAction.NEW_BRANCH: self.branch_button,
            ArchiveAction.NEW_PHASE: self.phase_button,
        }
        previews = build_previews(
            self.root, self.index, self.current_coordinate, self.state,
            self.result_combo.currentText(),
        )
        for action, button in buttons.items():
            preview = previews[action]
            button.setText(preview.text)
            button.setToolTip(preview.tooltip)
            button.setEnabled(preview.enabled)

    def archive(self, action: ArchiveAction) -> None:
        if not self.root:
            return
        try:
            receipt = self.archive_service.record(
                project_root=self.root,
                action=action,
                current=self.current_coordinate,
                state=self.state,
                result=self.result_combo.currentText(),
                artifacts=self.drop_zone.paths(),
                response=self.response_edit.toPlainText(),
                note=self.note_edit.text(),
            )
        except ArchiveStateError as error:
            self.refresh_project()
            self.reveal_path(error.destination.relative_to(self.root).as_posix())
            QMessageBox.warning(self, "Archive created; state recovery pending", str(error))
            return
        except ArchiveError as error:
            QMessageBox.warning(self, "Archive not created", str(error))
            return
        except Exception as error:
            QMessageBox.critical(self, "Archive failed", f"No workflow advance was recorded.\n\n{error}")
            return

        self.state = receipt.next_state
        self.last_handoff = receipt.handoff
        self.intake.clear_return()
        self.refresh_project()
        self.search_panel.reindex()
        self.reveal_path(receipt.destination.relative_to(self.root).as_posix())
        QMessageBox.information(
            self,
            "Interaction archived",
            f"{'Created' if receipt.created_coordinate else 'Recorded in'} "
            f"{receipt.destination.relative_to(self.root).as_posix()}\n\n"
            f"Next: {receipt.handoff}"
            + (f"\n\nWarning: {receipt.warning}" if receipt.warning else ""),
        )

    def paste_response(self) -> None:
        self.response_edit.setPlainText(QGuiApplication.clipboard().text())

    def reveal_path(self, relative_path: str) -> None:
        self.navigator.reveal(relative_path)

    def open_relative_path(self, relative_path: str) -> None:
        if self.root:
            self._open_path(self.root / relative_path)

    def _open_path(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def reopen_project(self) -> None:
        if not self.root or self.state.status != ProjectStatus.COMPLETE:
            return
        self.state = replace(self.state, status=ProjectStatus.IN_PROGRESS)
        StateStore(self.root).save(self.state)
        self.last_handoff = "Project reopened. Resume with the current agent."
        self._update_workflow()
        self._update_previews()

    def set_workflow_position(self) -> None:
        if not self.root:
            return
        current = describe_position(self.state)
        current_index = WORKFLOW_POSITIONS.index(current)
        position, accepted = QInputDialog.getItem(
            self,
            "Set workflow position",
            "Which agent response are you currently awaiting?",
            WORKFLOW_POSITIONS,
            current_index,
            False,
        )
        if not accepted or position == current:
            return
        try:
            receipt = record_alignment(self.root, self.state, position)
        except OSError as error:
            QMessageBox.warning(
                self,
                "Workflow position not saved",
                f"The project state could not be updated:\n{error}",
            )
            return
        self.state = receipt.state
        self.last_handoff = receipt.handoff
        self._update_workflow()
        self._update_previews()
        if receipt.warning:
            QMessageBox.warning(
                self,
                "Workflow position saved",
                receipt.warning,
            )

    def _last_handoff(self) -> str:
        if not self.root:
            return ""
        events = StateStore(self.root).read_events(limit=1)
        return str(events[-1].get("handoff", "")) if events else ""

    def closeEvent(self, event) -> None:
        self.search_panel.stop_indexing()
        event.accept()


def run(initial_root: Path | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Orchestra")
    app.setOrganizationName("Neuroca")
    window = MainWindow(initial_root)
    window.show()
    return app.exec()
