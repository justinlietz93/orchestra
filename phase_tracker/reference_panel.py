"""External reference search worker and shared results dialog.

One dialog serves every provider (arXiv, Crossref, PubMed, Semantic
Scholar). Qt lives here and in the thin button graft inside SearchPanel;
clients, records, BibTeX, and the exporter are pure modules. The dialog is
deliberately separate from the local results list so external results can
never be confused with, or wired into, project search selection, related
files, or the workbench.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .bibtex import format_bibliography
from .references import (
    ConnectorError,
    ExternalQueryOutcome,
    provider_label,
)
from .search import reference_exporter


class ExternalSearchWorker(QObject):
    finished = Signal(object, float)
    failed = Signal(str)

    def __init__(
        self,
        query: str,
        search_callable: Callable[[str], ExternalQueryOutcome],
    ) -> None:
        super().__init__()
        self.query = query
        self.search_callable = search_callable

    @Slot()
    def run(self) -> None:
        started = time.perf_counter()
        try:
            outcome = self.search_callable(self.query)
        except (ConnectorError, ValueError) as error:
            self.failed.emit(str(error))
            return
        duration_ms = (time.perf_counter() - started) * 1000.0
        self.finished.emit(outcome, duration_ms)


class ExternalResultsDialog(QDialog):
    """Read-only viewer for one external query outcome, with evidence export."""

    def __init__(
        self,
        outcome: ExternalQueryOutcome,
        search_duration_ms: float,
        root: Path | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.outcome = outcome
        self.search_duration_ms = search_duration_ms
        self.root = root
        label = provider_label(outcome.provider)
        self.setWindowTitle(f"{label} results — {outcome.query}")
        self.resize(940, 560)

        layout = QVBoxLayout(self)
        shown = len(outcome.references)
        summary = QLabel(
            f"{shown} results shown of {outcome.total_available} available on "
            f"{label} (external, non-authoritative)"
        )
        layout.addWidget(summary)

        body = QHBoxLayout()
        self.listing = QListWidget()
        self.listing.setWordWrap(True)
        for position, reference in enumerate(outcome.references, start=1):
            authors = ", ".join(reference.authors[:4])
            if len(reference.authors) > 4:
                authors += ", et al."
            meta_bits = [bit for bit in (reference.ref_id, reference.venue, authors) if bit]
            text = f"{position}. {reference.title}\n" + " · ".join(meta_bits)
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, position - 1)
            self.listing.addItem(item)
        self.listing.currentItemChanged.connect(self._show_details)
        self.listing.itemDoubleClicked.connect(self._open_reference_page)
        body.addWidget(self.listing, 1)

        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        body.addWidget(self.details, 1)
        layout.addLayout(body, 1)

        button_row = QHBoxLayout()
        self.status = QLabel("Double-click a result to open its page.")
        button_row.addWidget(self.status, 1)
        self.bibtex_button = QPushButton("Export BibTeX")
        self.bibtex_button.setEnabled(self.root is not None and shown > 0)
        self.bibtex_button.setToolTip(
            "Write all shown results as a .bib bibliography in "
            ".project-handoff/search-exports/."
        )
        self.bibtex_button.clicked.connect(self._export_bibtex)
        button_row.addWidget(self.bibtex_button)
        self.export_button = QPushButton("Export results")
        self.export_button.setEnabled(self.root is not None and shown > 0)
        self.export_button.setToolTip(
            "Write these results as a JSON observation in "
            ".project-handoff/search-exports/ "
            f"(schema: {reference_exporter.schema_id(outcome.provider)})."
        )
        self.export_button.clicked.connect(self._export)
        button_row.addWidget(self.export_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        if outcome.references:
            self.listing.setCurrentRow(0)

    def _selected_reference(self):
        item = self.listing.currentItem()
        if item is None:
            return None
        index = item.data(Qt.ItemDataRole.UserRole)
        return self.outcome.references[index]

    def _show_details(self, *_args) -> None:
        reference = self._selected_reference()
        if reference is None:
            self.details.clear()
            return
        parts = [f"<h3>{reference.title}</h3>"]
        if reference.authors:
            parts.append(f"<p><b>{', '.join(reference.authors)}</b></p>")
        meta = " · ".join(
            bit
            for bit in (
                reference.ref_id,
                reference.venue,
                f"published {reference.published}" if reference.published else "",
                f"DOI {reference.doi}" if reference.doi else "",
            )
            if bit
        )
        if meta:
            parts.append(f"<p>{meta}</p>")
        extra = reference.extra_dict()
        extra_line = " · ".join(
            f"{key.replace('_', ' ')}: {value}" for key, value in extra.items() if value
        )
        if extra_line:
            parts.append(f"<p><i>{extra_line}</i></p>")
        if reference.summary:
            parts.append(f"<p>{reference.summary}</p>")
        links = []
        if reference.url:
            links.append(f'<a href="{reference.url}">page</a>')
        if reference.pdf_url:
            links.append(f'<a href="{reference.pdf_url}">pdf</a>')
        if links:
            parts.append(f"<p>{' · '.join(links)}</p>")
        self.details.setHtml("".join(parts))

    def _open_reference_page(self, item: QListWidgetItem) -> None:
        reference = self._selected_reference()
        if reference is not None and reference.url:
            QDesktopServices.openUrl(QUrl(reference.url))

    def _export(self) -> None:
        if self.root is None:
            return
        captured = reference_exporter.capture(self.outcome, self.search_duration_ms)
        receipt = reference_exporter.write(self.root, captured)
        self.status.setText(
            f"Exported {receipt.result_count} results to {receipt.path.name}"
        )

    def _export_bibtex(self) -> None:
        if self.root is None:
            return
        header = (
            f"Generated by Orchestra from {provider_label(self.outcome.provider)} "
            f"query: {self.outcome.query}"
        )
        bibliography = format_bibliography(self.outcome.references, header)
        path = reference_exporter.write_bibliography(
            self.root, self.outcome, bibliography
        )
        self.status.setText(
            f"Exported {len(self.outcome.references)} BibTeX entries to {path.name}"
        )
