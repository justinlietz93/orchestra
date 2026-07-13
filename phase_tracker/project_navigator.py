from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, QItemSelectionModel, Qt, Signal
from PySide6.QtWidgets import (
    QFileSystemModel,
    QFrame,
    QLabel,
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

        layout = QVBoxLayout(self)
        title = QLabel("PROJECT FILES")
        title.setObjectName("eyebrow")
        layout.addWidget(title)

        self.model = QFileSystemModel(self)
        self.model.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden
        )
        self.model.setReadOnly(True)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.doubleClicked.connect(self._open_selected)
        self.tree.setColumnWidth(0, 250)
        for column in (1, 2, 3):
            self.tree.setColumnHidden(column, True)
        layout.addWidget(self.tree, 1)

    def set_root(self, root: Path) -> None:
        self.root = root.resolve()
        self.model.setRootPath(str(self.root))
        self.tree.setRootIndex(self.model.index(str(self.root)))

    def reveal(self, relative_path: str) -> None:
        if not self.root:
            return
        index = self.model.index(str(self.root / relative_path))
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

    def _open_selected(self, index) -> None:
        self.open_requested.emit(self.model.filePath(index))

