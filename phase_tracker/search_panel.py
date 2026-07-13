from __future__ import annotations

import re
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .search_engine import ProjectSearchIndex, SearchResult
from .search import SearchResultsExporter


class IndexWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, root: Path):
        super().__init__()
        self.root = root
        self.cancelled = False

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(
                ProjectSearchIndex(self.root).rebuild(lambda: self.cancelled)
            )
        except Exception as error:
            self.failed.emit(str(error))

    def cancel(self) -> None:
        self.cancelled = True


class SearchPanel(QFrame):
    reveal_requested = Signal(str)
    open_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.root: Path | None = None
        self.index: ProjectSearchIndex | None = None
        self.thread: QThread | None = None
        self.worker: IndexWorker | None = None
        self.results_by_node: dict[int, SearchResult] = {}
        self.last_export: dict[str, object] | None = None
        self.pending_reindex = False

        layout = QVBoxLayout(self)
        title = QLabel("PROJECT SEARCH")
        title.setObjectName("eyebrow")
        layout.addWidget(title)

        query_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Ask: what failed around parity seating?")
        self.query.returnPressed.connect(self.run_search)
        self.search_button = QPushButton("Search")
        self.search_button.setObjectName("primary")
        self.search_button.clicked.connect(self.run_search)
        self.index_button = QPushButton("Reindex")
        self.index_button.clicked.connect(self.reindex)
        query_row.addWidget(self.query, 1)
        query_row.addWidget(self.search_button)
        query_row.addWidget(self.index_button)
        layout.addLayout(query_row)

        status_row = QHBoxLayout()
        self.status = QLabel("Choose a project root to build its local index")
        self.status.setObjectName("muted")
        self.export_button = QPushButton("Export results")
        self.export_button.setEnabled(False)
        self.export_button.setToolTip(
            "Write this query to .project-handoff/search-exports/"
        )
        self.export_button.clicked.connect(self.export_results)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.export_button)
        layout.addLayout(status_row)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.results = QListWidget()
        self.results.currentItemChanged.connect(self._show_related)
        self.results.itemDoubleClicked.connect(self._open_result)
        self.related = QListWidget()
        self.related.itemDoubleClicked.connect(self._open_related)

        result_box = QWidget()
        result_layout = QVBoxLayout(result_box)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_label = QLabel("MATCHES")
        result_label.setObjectName("eyebrow")
        result_layout.addWidget(result_label)
        result_layout.addWidget(self.results)

        related_box = QWidget()
        related_layout = QVBoxLayout(related_box)
        related_layout.setContentsMargins(0, 0, 0, 0)
        related_label = QLabel("SAME ARCHIVED INTERACTION")
        related_label.setObjectName("eyebrow")
        related_layout.addWidget(related_label)
        related_layout.addWidget(self.related)

        splitter.addWidget(result_box)
        splitter.addWidget(related_box)
        splitter.setSizes([360, 180])
        layout.addWidget(splitter, 1)

    def set_root(self, root: Path, auto_index: bool = True) -> None:
        self.root = root.resolve()
        self.index = ProjectSearchIndex(self.root)
        self.last_export = None
        self.export_button.setEnabled(False)
        self.results.clear()
        self.related.clear()
        if self.index.db_path.exists():
            self.status.setText("Index ready. Reindex after external file changes.")
        elif auto_index:
            self.reindex()

    def reindex(self) -> None:
        if not self.root:
            return
        if self.thread:
            self.pending_reindex = True
            return
        self.pending_reindex = False
        self.status.setText("Indexing file content and provenance graph…")
        self.index_button.setEnabled(False)
        self.search_button.setEnabled(False)
        thread = QThread(self)
        worker = IndexWorker(self.root)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._index_finished)
        worker.failed.connect(self._index_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._thread_finished)
        self.thread = thread
        self.worker = worker
        thread.start()

    def run_search(self) -> None:
        if not self.index:
            return
        if self.thread:
            self.status.setText("Wait for indexing to finish before searching")
            return
        self.last_export = None
        self.export_button.setEnabled(False)
        started = time.perf_counter()
        try:
            results = self.index.search(self.query.text())
        except Exception as error:
            self.status.setText(f"Search failed: {error}")
            return
        duration_ms = (time.perf_counter() - started) * 1000
        try:
            self.last_export = SearchResultsExporter(self.index).capture(
                self.query.text(),
                results,
                search_duration_ms=duration_ms,
            )
            self.export_button.setEnabled(True)
        except Exception as error:
            capture_error = str(error)
        else:
            capture_error = ""
        self.results.clear()
        self.related.clear()
        self.results_by_node.clear()
        for result in results:
            coordinate = ""
            if result.phase is not None:
                coordinate = f"p{result.phase}"
                if result.branch is not None:
                    coordinate += f"-b{result.branch}"
                if result.version is not None:
                    coordinate += f"-v{result.version}"
            snippet = re.sub(r"</?mark>", "", result.snippet)
            snippet = " ".join(snippet.split())
            text = f"{result.name}\n{coordinate or result.kind} · {snippet[:220]}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, result.path)
            item.setData(Qt.ItemDataRole.UserRole + 1, result.node_id)
            item.setToolTip(result.path)
            self.results.addItem(item)
            self.results_by_node[result.node_id] = result
        if capture_error:
            self.status.setText(f"Results shown; export unavailable: {capture_error}")
        else:
            self.status.setText(
                f"{len(results)} ranked match{'es' if len(results) != 1 else ''}"
            )
        if results:
            self.results.setCurrentRow(0)

    def export_results(self) -> None:
        if not self.index or not self.root or not self.last_export:
            return
        try:
            receipt = SearchResultsExporter(self.index).write(self.last_export)
        except Exception as error:
            self.status.setText(f"Export failed: {error}")
            return
        relative = receipt.path.relative_to(self.root).as_posix()
        self.status.setText(
            f"Exported {receipt.ranked_match_count}: search-exports/{receipt.path.name}"
        )
        self.status.setToolTip(relative)

    @Slot(object)
    def _index_finished(self, summary: dict[str, int]) -> None:
        if summary.get("cancelled"):
            self.status.setText("Indexing cancelled")
        else:
            self.status.setText(
                f"Indexed {summary['indexed_files']} files across {summary['nodes']} graph nodes"
            )

    @Slot(str)
    def _index_failed(self, message: str) -> None:
        self.status.setText(f"Indexing failed: {message}")

    @Slot()
    def _thread_finished(self) -> None:
        if self.thread:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None
        self.index_button.setEnabled(True)
        self.search_button.setEnabled(True)
        if self.pending_reindex:
            self.pending_reindex = False
            self.reindex()

    def _show_related(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self.related.clear()
        if not current or not self.index:
            return
        node_id = current.data(Qt.ItemDataRole.UserRole + 1)
        result = self.results_by_node.get(int(node_id)) if node_id is not None else None
        if not result:
            return
        self.reveal_requested.emit(result.path)
        for related in self.index.related_files(result.node_id):
            item = QListWidgetItem(related.name)
            item.setData(Qt.ItemDataRole.UserRole, related.path)
            item.setToolTip(related.path)
            self.related.addItem(item)

    def _open_result(self, item: QListWidgetItem) -> None:
        self.open_requested.emit(str(item.data(Qt.ItemDataRole.UserRole)))

    def _open_related(self, item: QListWidgetItem) -> None:
        self.open_requested.emit(str(item.data(Qt.ItemDataRole.UserRole)))

    def stop_indexing(self) -> None:
        self.pending_reindex = False
        if not self.thread or not self.worker:
            return
        self.worker.cancel()
        self.thread.requestInterruption()
        self.thread.quit()
        self.thread.wait(10000)
