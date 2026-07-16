from __future__ import annotations

import re
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .batch_query_dialog import BatchQueryDialog
from .search_engine import ProjectSearchIndex, SearchResult
from .search import BatchExportReport, SearchResultsExporter, export_batch_queries
from .search_query import parse_search_query
from .workbench.launcher import WorkbenchLaunchBar
from . import arxiv_client, crossref_client, pubmed_client, semantic_scholar_client
from .reference_panel import ExternalResultsDialog, ExternalSearchWorker
from .references import from_arxiv, provider_label
from .activity_log import ActivityLog


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


class BatchSearchWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, root: Path, queries: list[str]):
        super().__init__()
        self.root = root
        self.queries = queries
        self._cancelled = False

    @Slot()
    def run(self) -> None:
        try:
            report = export_batch_queries(
                ProjectSearchIndex(self.root),
                self.queries,
                progress=self.progress.emit,
                cancelled=lambda: self._cancelled,
            )
            self.finished.emit(report)
        except Exception as error:
            self.failed.emit(str(error))

    def cancel(self) -> None:
        self._cancelled = True


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
        self.batch_thread: QThread | None = None
        self.activity: ActivityLog | None = None
        self.external_provider: str | None = None
        self.external_thread: QThread | None = None
        self.external_worker: ExternalSearchWorker | None = None
        self.batch_worker: BatchSearchWorker | None = None
        self.batch_progress: QProgressDialog | None = None
        self.results_by_node: dict[int, SearchResult] = {}
        self.last_export: dict[str, object] | None = None
        self.pending_reindex = False

        layout = QVBoxLayout(self)
        title = QLabel("PROJECT SEARCH")
        title.setObjectName("eyebrow")
        layout.addWidget(title)

        query_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText('Search broadly, or use "quotes" for an exact phrase')
        self.query.setToolTip(
            'Words inside double quotes must occur together and in order. '
            "Unquoted words keep broad search behavior."
        )
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

        external_row = QHBoxLayout()
        external_label = QLabel("External:")
        external_label.setToolTip(
            "Search public literature providers with the query above. "
            "Results are external observations and never enter the project index."
        )
        external_row.addWidget(external_label)
        self.external_buttons: dict[str, QPushButton] = {}
        for provider in ("arxiv", "crossref", "pubmed", "semanticscholar"):
            button = QPushButton(provider_label(provider))
            button.clicked.connect(
                lambda _checked=False, name=provider: self.run_external_search(name)
            )
            self.external_buttons[provider] = button
            external_row.addWidget(button)
        external_row.addStretch(1)
        layout.addLayout(external_row)

        self.workbench_launcher = WorkbenchLaunchBar()
        self.workbench_launcher.attachment_created.connect(
            lambda _path: self.reindex()
        )
        layout.addWidget(self.workbench_launcher)

        status_row = QHBoxLayout()
        self.status = QLabel("Choose a project root to build its local index")
        self.status.setObjectName("muted")
        self.export_button = QPushButton("Export results")
        self.export_button.setEnabled(False)
        self.export_button.setToolTip(
            "Write this query to .project-handoff/search-exports/"
        )
        self.export_button.clicked.connect(self.export_results)
        self.batch_button = QPushButton("Batch queries…")
        self.batch_button.setEnabled(False)
        self.batch_button.setToolTip(
            "Run and export multiple newline- or comma-separated queries"
        )
        self.batch_button.clicked.connect(self.open_batch_queries)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.batch_button)
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
        self.stop_batch()
        self.root = root.resolve()
        self.index = ProjectSearchIndex(self.root)
        self.workbench_launcher.set_root(self.root)
        self.activity = ActivityLog(self.root)
        self.last_export = None
        self.export_button.setEnabled(False)
        self.results.clear()
        self.related.clear()
        if self.index.db_path.exists():
            self.status.setText("Index ready. Reindex after external file changes.")
            self.batch_button.setEnabled(True)
        elif auto_index:
            self.reindex()
        else:
            self.batch_button.setEnabled(False)

    def reindex(self) -> None:
        if not self.root:
            return
        if self.batch_thread:
            self.pending_reindex = True
            self.status.setText("Reindex queued until the batch export finishes")
            return
        if self.thread:
            self.pending_reindex = True
            return
        self.pending_reindex = False
        self.status.setText("Indexing file content and provenance graph…")
        self.index_button.setEnabled(False)
        self.search_button.setEnabled(False)
        self.batch_button.setEnabled(False)
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
        if self.batch_thread:
            self.status.setText("Wait for the batch export to finish before searching")
            return
        if self.thread:
            self.status.setText("Wait for indexing to finish before searching")
            return
        self.last_export = None
        self.export_button.setEnabled(False)
        started = time.perf_counter()
        parsed_query = parse_search_query(self.query.text())
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
        self.workbench_launcher.clear_selection()
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
            badge_text = " · ".join(result.badges)
            prefix = f"[{badge_text}]\n" if badge_text else ""
            text = (
                f"{prefix}{result.name}\n"
                f"{coordinate or result.kind} · {snippet[:220]}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, result.path)
            item.setData(Qt.ItemDataRole.UserRole + 1, result.node_id)
            item.setToolTip(result.path)
            self.results.addItem(item)
            self.results_by_node[result.node_id] = result
        if self.activity:
            self.activity.record(
                "local_search",
                query=self.query.text(),
                mode=parsed_query.match_mode,
                result_count=len(results),
                duration_ms=round(duration_ms, 2),
                capture_error=capture_error,
            )
        if capture_error:
            self.status.setText(f"Results shown; export unavailable: {capture_error}")
        else:
            mode_label = {
                "broad_terms": "broad terms",
                "quoted_phrase": "exact phrase",
                "mixed": "exact phrase + broad terms",
                "empty": "empty query",
            }[parsed_query.match_mode]
            self.status.setText(
                f"{len(results)} ranked match{'es' if len(results) != 1 else ''}"
                f" · {mode_label}"
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
        if self.activity:
            self.activity.record(
                "export_search_json",
                file=receipt.path.name,
                result_count=receipt.ranked_match_count,
            )
        self.status.setText(
            f"Exported {receipt.ranked_match_count}: search-exports/{receipt.path.name}"
        )
        self.status.setToolTip(relative)

    def open_batch_queries(self) -> None:
        if not self.root or not self.index or not self.index.db_path.exists():
            self.status.setText("Build the search index before running a batch")
            return
        if self.thread or self.batch_thread:
            self.status.setText("Wait for current search work to finish")
            return

        dialog = BatchQueryDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            queries = dialog.queries()
        except ValueError as error:
            self.status.setText(str(error))
            return
        if not queries:
            return
        self._start_batch(queries)

    def _start_batch(self, queries: list[str]) -> None:
        assert self.root is not None
        self.search_button.setEnabled(False)
        self.index_button.setEnabled(False)
        self.batch_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.status.setText(f"Starting batch of {len(queries)} queries…")

        progress = QProgressDialog(
            "Preparing batch search…",
            "Cancel",
            0,
            len(queries),
            self,
        )
        progress.setWindowTitle("Batch search and export")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        thread = QThread(self)
        worker = BatchSearchWorker(self.root, queries)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._batch_progressed)
        worker.finished.connect(self._batch_finished)
        worker.failed.connect(self._batch_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._batch_thread_finished)
        progress.canceled.connect(self._cancel_batch)

        self.batch_progress = progress
        self.batch_thread = thread
        self.batch_worker = worker
        progress.show()
        thread.start()

    @Slot(int, int, str)
    def _batch_progressed(self, position: int, total: int, query: str) -> None:
        if not self.batch_progress:
            return
        compact_query = " ".join(query.split())
        if len(compact_query) > 80:
            compact_query = compact_query[:77] + "…"
        self.batch_progress.setLabelText(
            f"Processed {position} of {total}\n{compact_query}"
        )
        self.batch_progress.setValue(position)

    @Slot()
    def _cancel_batch(self) -> None:
        if self.batch_worker:
            self.batch_worker.cancel()

    @Slot(object)
    def _batch_finished(self, report: BatchExportReport) -> None:
        if self.batch_progress:
            self.batch_progress.close()
        exported = len(report.receipts)
        if self.activity:
            self.activity.record(
                "batch",
                query_count=report.query_count,
                completed=report.completed_query_count,
                exported=exported,
                failed=len(report.failures),
                cancelled=bool(report.cancelled),
            )
        if report.cancelled:
            self.status.setText(
                f"Batch cancelled after {report.completed_query_count} of "
                f"{report.query_count}; {exported} exported"
            )
        elif report.failures:
            self.status.setText(
                f"Batch {report.batch_execution_id}: {exported} exported, "
                f"{len(report.failures)} failed"
            )
            details = "\n".join(
                f"{failure.position}. {failure.query}: {failure.message}"
                for failure in report.failures[:8]
            )
            QMessageBox.warning(
                self,
                "Batch export completed with errors",
                f"{exported} of {report.query_count} queries were exported.\n\n"
                f"{details}",
            )
        else:
            self.status.setText(
                f"Exported {exported} batched queries · "
                f"{report.batch_execution_id}"
            )
        self.status.setToolTip(
            ".project-handoff/search-exports/\n"
            f"Batch: {report.batch_execution_id}"
        )

    @Slot(str)
    def _batch_failed(self, message: str) -> None:
        if self.batch_progress:
            self.batch_progress.close()
        self.status.setText(f"Batch export failed: {message}")
        QMessageBox.warning(self, "Batch export failed", message)

    @Slot()
    def _batch_thread_finished(self) -> None:
        if self.batch_thread:
            self.batch_thread.deleteLater()
        self.batch_worker = None
        self.batch_thread = None
        self.batch_progress = None
        self.index_button.setEnabled(True)
        self.search_button.setEnabled(True)
        self.batch_button.setEnabled(
            bool(self.index and self.index.db_path.exists())
        )
        self.export_button.setEnabled(self.last_export is not None)
        if self.pending_reindex:
            self.pending_reindex = False
            self.reindex()

    @Slot(object)
    def _index_finished(self, summary: dict[str, int]) -> None:
        if summary.get("cancelled"):
            self.status.setText("Indexing cancelled")
        else:
            self.status.setText(
                f"Indexed {summary['indexed_files']} files across {summary['nodes']} graph nodes"
            )
        if self.activity:
            self.activity.record(
                "reindex",
                cancelled=bool(summary.get("cancelled")),
                file_count=summary.get("indexed_files"),
                nodes=summary.get("nodes"),
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
        self.batch_button.setEnabled(
            bool(self.index and self.index.db_path.exists())
        )
        if self.pending_reindex:
            self.pending_reindex = False
            self.reindex()

    def _show_related(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self.related.clear()
        if not current or not self.index:
            self.workbench_launcher.clear_selection()
            return
        node_id = current.data(Qt.ItemDataRole.UserRole + 1)
        result = self.results_by_node.get(int(node_id)) if node_id is not None else None
        if not result:
            self.workbench_launcher.clear_selection()
            return
        self.workbench_launcher.set_selection(result.path, result.kind)
        self.reveal_requested.emit(result.path)
        for related in self.index.related_files(result.node_id):
            badge_text = " · ".join(related.badges)
            prefix = f"[{badge_text}] " if badge_text else ""
            item = QListWidgetItem(f"{prefix}{related.name}")
            item.setData(Qt.ItemDataRole.UserRole, related.path)
            item.setToolTip(related.path)
            self.related.addItem(item)

    def _open_result(self, item: QListWidgetItem) -> None:
        self.open_requested.emit(str(item.data(Qt.ItemDataRole.UserRole)))

    def _open_related(self, item: QListWidgetItem) -> None:
        self.open_requested.emit(str(item.data(Qt.ItemDataRole.UserRole)))

    def stop_indexing(self) -> None:
        self.pending_reindex = False
        self.workbench_launcher.finish_background()
        if not self.thread or not self.worker:
            return
        self.worker.cancel()
        self.thread.requestInterruption()
        self.thread.quit()
        self.thread.wait(10000)

    def stop_batch(self) -> None:
        if self.batch_progress:
            self.batch_progress.close()
        if not self.batch_thread or not self.batch_worker:
            return
        self.batch_worker.cancel()
        self.batch_thread.requestInterruption()
        self.batch_thread.quit()
        self.batch_thread.wait(10000)

    _EXTERNAL_SEARCHERS = {
        "arxiv": staticmethod(lambda query: from_arxiv(arxiv_client.search(query))),
        "crossref": staticmethod(crossref_client.search),
        "pubmed": staticmethod(pubmed_client.search),
        "semanticscholar": staticmethod(semantic_scholar_client.search),
    }

    def run_external_search(self, provider: str) -> None:
        query = self.query.text().strip()
        label = provider_label(provider)
        if not query:
            self.status.setText(f"Enter a query to search {label}.")
            return
        if self.external_thread is not None:
            self.status.setText("An external search is already running.")
            return
        for button in self.external_buttons.values():
            button.setEnabled(False)
        self.external_provider = provider
        self.status.setText(f"Searching {label} for: {query}")
        searcher = self._EXTERNAL_SEARCHERS[provider].__func__
        self.external_thread = QThread(self)
        self.external_worker = ExternalSearchWorker(query, searcher)
        self.external_worker.moveToThread(self.external_thread)
        self.external_thread.started.connect(self.external_worker.run)
        self.external_worker.finished.connect(self._external_finished)
        self.external_worker.failed.connect(self._external_failed)
        self.external_thread.start()

    def _external_teardown(self) -> None:
        if self.external_thread is not None:
            self.external_thread.quit()
            self.external_thread.wait()
        self.external_thread = None
        self.external_worker = None
        for button in self.external_buttons.values():
            button.setEnabled(True)

    def _external_finished(self, outcome, duration_ms: float) -> None:
        self._external_teardown()
        if self.activity:
            self.activity.record(
                "external_search",
                provider=outcome.provider,
                query=outcome.query,
                ok=True,
                result_count=len(outcome.references),
                total_available=outcome.total_available,
                duration_ms=round(duration_ms, 2),
            )
        label = provider_label(outcome.provider)
        self.status.setText(
            f"{label}: {len(outcome.references)} of {outcome.total_available} "
            f"results for: {outcome.query}"
        )
        dialog = ExternalResultsDialog(outcome, duration_ms, self.root, self)
        dialog.exec()

    def _external_failed(self, message: str) -> None:
        self._external_teardown()
        if self.activity and self.external_provider is not None:
            self.activity.record(
                "external_search",
                provider=self.external_provider,
                query=self.query.text(),
                ok=False,
                error=message,
            )
        self.status.setText(f"External search failed: {message}")

    def stop_external(self) -> None:
        if self.external_thread is not None:
            self.external_thread.quit()
            self.external_thread.wait()
            self.external_thread = None
            self.external_worker = None

    def stop_background_work(self) -> None:
        self.stop_indexing()
        self.stop_batch()
        self.stop_external()
