from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, QItemSelectionModel, QSize, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFileSystemModel,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStyle,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)


class ProjectNavigator(QFrame):
    open_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.root: Path | None = None
        self._expanded: set[str] = set()
        self._pending_reveal: str | None = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("PROJECT FILES")
        title.setObjectName("eyebrow")
        self.refresh_button = QToolButton()
        self.refresh_button.setObjectName("treeRefresh")
        self.refresh_button.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_BrowserReload
            )
        )
        self.refresh_button.setIconSize(QSize(15, 15))
        self.refresh_button.setFixedSize(24, 24)
        self.refresh_button.setToolTip("Refresh file tree")
        self.refresh_button.setAccessibleName("Refresh file tree")
        self.refresh_button.clicked.connect(lambda: self.refresh())
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.tree = QTreeView()
        self.tree.setSortingEnabled(True)
        self.tree.doubleClicked.connect(self._open_selected)
        self.model = self._new_model()
        self._attach_model()
        layout.addWidget(self.tree, 1)

    def set_root(self, root: Path) -> None:
        self.refresh(root)

    def refresh(self, root: Path | None = None) -> None:
        root_changed = False
        if root is not None:
            resolved = root.resolve()
            root_changed = resolved != self.root
            if root_changed:
                self._expanded.clear()
                self._pending_reveal = None
            self.root = resolved
        if not self.root:
            return
        if not root_changed:
            self._remember_view()
        previous = self.model
        self.model = self._new_model()
        self._attach_model()
        root_index = self.model.setRootPath(str(self.root))
        self.tree.setRootIndex(root_index)
        previous.deleteLater()
        QTimer.singleShot(0, self._restore_view)

    def reveal(self, relative_path: str) -> None:
        if not self.root:
            return
        self._pending_reveal = str(self.root / relative_path)
        self._restore_view()

    def _new_model(self) -> QFileSystemModel:
        model = QFileSystemModel(self)
        model.setFilter(
            QDir.Filter.AllEntries
            | QDir.Filter.NoDotAndDotDot
            | QDir.Filter.Hidden
        )
        model.setReadOnly(True)
        model.directoryLoaded.connect(
            lambda _path: QTimer.singleShot(0, self._restore_view)
        )
        return model

    def _attach_model(self) -> None:
        self.tree.setModel(self.model)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.setColumnWidth(0, 250)
        for column in (1, 2, 3):
            self.tree.setColumnHidden(column, True)

    def _remember_view(self) -> None:
        root_index = self.tree.rootIndex()
        if not root_index.isValid():
            return
        self._expanded = set()
        pending = [root_index]
        while pending:
            parent = pending.pop()
            for row in range(self.model.rowCount(parent)):
                child = self.model.index(row, 0, parent)
                if self.model.isDir(child) and self.tree.isExpanded(child):
                    self._expanded.add(self.model.filePath(child))
                    pending.append(child)
        current = self.tree.currentIndex()
        if current.isValid():
            self._pending_reveal = self.model.filePath(current)

    def _restore_view(self) -> None:
        for path in sorted(self._expanded, key=lambda value: value.count("/")):
            index = self.model.index(path)
            if index.isValid():
                self.tree.expand(index)
        if not self._pending_reveal:
            return
        index = self.model.index(self._pending_reveal)
        if not index.isValid():
            return
        parent = index.parent()
        while parent.isValid():
            self.tree.expand(parent)
            parent = parent.parent()
        self.tree.selectionModel().select(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )
        self.tree.scrollTo(index)
        self._pending_reveal = None

    def _open_selected(self, index) -> None:
        self.open_requested.emit(self.model.filePath(index))
