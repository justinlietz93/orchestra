from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..discovery import VERSION_PATTERN, scan_project
from .attachments import WorkbenchAttachmentService
from .domain import ResearchRunReceipt, WorkflowReference
from .services import ResearchWorkbenchService
from .view import WorkbenchForm


class RunWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        root: Path,
        objective: str,
        graph_node_path: str,
        selected_paths: tuple[Path, ...],
    ):
        super().__init__()
        self.root = root
        self.objective = objective
        self.graph_node_path = graph_node_path
        self.selected_paths = selected_paths

    @Slot()
    def run(self) -> None:
        try:
            receipt = ResearchWorkbenchService(self.root).create_campaign_run(
                self.objective,
                self.graph_node_path,
                self.selected_paths,
            )
            self.finished.emit(receipt)
        except Exception as error:
            self.failed.emit(str(error))


class ResearchWorkbenchWindow(QDialog):
    attachment_created = Signal(str)

    def __init__(
        self,
        project_root: Path,
        graph_node_path: str,
        graph_node_kind: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Orchestra · User Research Workbench")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(900, 780)
        self.root = project_root.expanduser().resolve()
        self.graph_node_path = graph_node_path
        self.graph_node_kind = graph_node_kind
        self.artifacts: dict[str, Path] = {}
        self.run_receipt: ResearchRunReceipt | None = None
        self.thread: QThread | None = None
        self.worker: RunWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.form = WorkbenchForm(graph_node_path)
        layout.addWidget(self.form)
        self.form.add_button.clicked.connect(self.add_files)
        self.form.remove_button.clicked.connect(self.remove_selected)
        self.form.run_button.clicked.connect(self.start_run)
        self.form.attach_button.clicked.connect(self.attach_summary)
        self._populate_targets()
        if graph_node_kind == "file":
            self._add_path(self.root / graph_node_path)

    def _populate_targets(self) -> None:
        preferred = self._node_coordinate()
        index = scan_project(self.root)
        if index.duplicate_phases:
            self.form.run_status.setText(
                "Attachment disabled: duplicate phase numbers are ambiguous"
            )
            return
        for phase_number, phase in sorted(index.phases.items()):
            for branch_number, branch in sorted(phase.branches.items()):
                for version in branch.versions:
                    reference = WorkflowReference(
                        phase_number,
                        branch_number,
                        version,
                        phase.path.name,
                    )
                    relative = reference.relative_path().as_posix()
                    self.form.target.addItem(relative, reference)
                    if preferred == (
                        phase_number,
                        branch_number,
                        version,
                    ):
                        self.form.target.setCurrentIndex(
                            self.form.target.count() - 1
                        )

    def _node_coordinate(self) -> tuple[int, int, int] | None:
        for part in Path(self.graph_node_path).parts:
            match = VERSION_PATTERN.fullmatch(part)
            if match:
                return (
                    int(match.group("phase")),
                    int(match.group("branch")),
                    int(match.group("version")),
                )
        return None

    def add_files(self) -> None:
        start = self.root / self.graph_node_path
        if not start.is_dir():
            start = start.parent
        selected, _filter = QFileDialog.getOpenFileNames(
            self,
            "Select explicit internal research artifacts",
            str(start if start.is_dir() else self.root),
        )
        for value in selected:
            self._add_path(Path(value))

    def _add_path(self, path: Path) -> None:
        candidate = path.expanduser()
        if candidate.is_symlink():
            QMessageBox.warning(
                self,
                "Symlinked artifact",
                f"Research snapshots do not follow symlinks:\n{candidate}",
            )
            return
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError:
            QMessageBox.warning(
                self,
                "Artifact outside project",
                f"Select files beneath the project root:\n{resolved}",
            )
            return
        if not resolved.is_file() or resolved.is_symlink():
            return
        key = relative.as_posix()
        if key not in self.artifacts:
            self.artifacts[key] = resolved
            self.form.artifact_list.addItem(key)

    def remove_selected(self) -> None:
        for item in self.form.artifact_list.selectedItems():
            self.artifacts.pop(item.text(), None)
            self.form.artifact_list.takeItem(
                self.form.artifact_list.row(item)
            )

    def start_run(self) -> None:
        if self.thread:
            return
        objective = self.form.objective.text().strip()
        if not objective or not self.artifacts:
            QMessageBox.warning(
                self,
                "Run not started",
                "Enter a campaign objective and select at least one project file.",
            )
            return
        self.form.run_button.setEnabled(False)
        self.form.run_status.setText("Creating exact snapshots and summary…")
        thread = QThread(self)
        worker = RunWorker(
            self.root,
            objective,
            self.graph_node_path,
            tuple(self.artifacts.values()),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._run_finished)
        worker.failed.connect(self._run_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        self.thread = thread
        self.worker = worker
        thread.start()

    @Slot(object)
    def _run_finished(self, receipt: ResearchRunReceipt) -> None:
        self.run_receipt = receipt
        self.form.summary.setPlainText(receipt.summary_text)
        self.form.run_status.setText(
            f"{receipt.run_id} · SHA-256 {receipt.summary_sha256[:16]}…"
        )
        self.form.attach_button.setEnabled(self.form.target.count() > 0)

    @Slot(str)
    def _run_failed(self, message: str) -> None:
        self.form.run_status.setText("Run failed")
        QMessageBox.warning(self, "Research run failed", message)

    @Slot()
    def _thread_finished(self) -> None:
        if self.thread:
            self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.form.run_button.setEnabled(self.run_receipt is None)

    def attach_summary(self) -> None:
        if not self.run_receipt:
            return
        reference = self.form.target.currentData()
        if not isinstance(reference, WorkflowReference):
            return
        try:
            receipt = WorkbenchAttachmentService(self.root).attach(
                self.run_receipt,
                reference,
                self.form.note.text(),
            )
        except Exception as error:
            QMessageBox.warning(self, "Attachment failed", str(error))
            return
        self.form.lifecycle_badge.setText("ATTACHED")
        self.form.attach_button.setEnabled(False)
        relative = receipt.destination.relative_to(self.root).as_posix()
        self.form.run_status.setText(f"Attached: {relative}")
        self.attachment_created.emit(relative)
        QMessageBox.information(
            self,
            "User research attached",
            f"Attached to {relative}\n\nNo agent exposure event was created.",
        )

    def closeEvent(self, event) -> None:
        if self.thread:
            self.form.run_status.setText(
                "Wait for the immutable run to finish before closing"
            )
            event.ignore()
            return
        event.accept()

    def finish_background(self) -> None:
        if self.thread:
            self.thread.quit()
            self.thread.wait()
