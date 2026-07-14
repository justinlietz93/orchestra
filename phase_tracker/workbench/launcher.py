from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .window import ResearchWorkbenchWindow


class WorkbenchLaunchBar(QWidget):
    attachment_created = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.root: Path | None = None
        self.node_path: str | None = None
        self.node_kind: str | None = None
        self.window: ResearchWorkbenchWindow | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("USER RESEARCH WORKBENCH")
        label.setObjectName("eyebrow")
        self.button = QPushButton("Research selected graph node")
        self.button.setEnabled(False)
        self.button.clicked.connect(self.open_workbench)
        layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(self.button)

    def set_root(self, root: Path) -> None:
        self.root = root.resolve()
        self.clear_selection()

    def set_selection(self, node_path: str, node_kind: str) -> None:
        self.node_path = node_path
        self.node_kind = node_kind
        self.button.setEnabled(self.root is not None)

    def clear_selection(self) -> None:
        self.node_path = None
        self.node_kind = None
        self.button.setEnabled(False)

    def open_workbench(self) -> None:
        if not self.root or not self.node_path or not self.node_kind:
            return
        if self.window and self.window.isVisible():
            self.window.raise_()
            self.window.activateWindow()
            return
        window = ResearchWorkbenchWindow(
            self.root,
            self.node_path,
            self.node_kind,
            self,
        )
        window.attachment_created.connect(self.attachment_created)
        window.destroyed.connect(self._window_destroyed)
        self.window = window
        window.show()

    def finish_background(self) -> None:
        if self.window:
            self.window.finish_background()

    def _window_destroyed(self, *_args: object) -> None:
        self.window = None
