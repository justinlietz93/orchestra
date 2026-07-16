"""Minimal SQL editor over the derived analytics database.

Embedded as a tab inside the Analytics dock view — not a window.

The connection it receives is the disposable in-memory read-model with
`PRAGMA query_only = ON` and the workbench attached read-only — every
statement is physically incapable of writing to any ledger. Saved queries
become named table views rendered in the analytics dashboard.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, Signal

from . import analytics_db

STARTER_QUERY = (
    "SELECT judge, judged,\n"
    "       SUM(is_pass) AS passes, SUM(is_fail) AS failures,\n"
    "       ROUND(1.0 * SUM(is_pass) / NULLIF(SUM(is_pass) + SUM(is_fail), 0), 3)\n"
    "         AS pass_rate\n"
    "FROM judgments\n"
    "GROUP BY judge, judged\n"
    "ORDER BY judge, judged;"
)


class QueryEditorWidget(QWidget):
    views_changed = Signal()

    def __init__(
        self,
        get_connection,
        root: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.get_connection = get_connection
        self.root = root

        layout = QVBoxLayout(self)
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Saved queries:"))
        self.saved_combo = QComboBox()
        self.saved_combo.setMinimumWidth(240)
        top_row.addWidget(self.saved_combo)
        load_button = QPushButton("Load")
        load_button.clicked.connect(self._load_selected)
        top_row.addWidget(load_button)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self._delete_selected)
        top_row.addWidget(delete_button)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        schema_panel = QWidget()
        schema_layout = QVBoxLayout(schema_panel)
        schema_layout.setContentsMargins(0, 0, 0, 0)
        schema_layout.addWidget(QLabel("Tables (double-click to insert)"))
        self.schema_list = QListWidget()
        self.reload_schema()
        self.schema_list.itemDoubleClicked.connect(
            lambda item: self.editor.insertPlainText(item.text().strip())
        )
        schema_layout.addWidget(self.schema_list)
        splitter.addWidget(schema_panel)

        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(STARTER_QUERY)
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.editor.setFont(font)
        editor_layout.addWidget(self.editor, 1)

        button_row = QHBoxLayout()
        self.status = QLabel("Ctrl+Enter runs the query.")
        button_row.addWidget(self.status, 1)
        run_button = QPushButton("Run")
        run_button.setShortcut("Ctrl+Return")
        run_button.clicked.connect(self.run_current)
        button_row.addWidget(run_button)
        save_button = QPushButton("Save as view…")
        save_button.setToolTip(
            "Save this query by name; it renders as a table in the "
            "analytics dashboard on every refresh."
        )
        save_button.clicked.connect(self._save_as_view)
        button_row.addWidget(save_button)
        editor_layout.addLayout(button_row)

        self.results = QTableWidget(0, 0)
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        editor_layout.addWidget(self.results, 2)

        splitter.addWidget(editor_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 770])
        layout.addWidget(splitter, 1)

        self._reload_saved()

    def reload_schema(self) -> None:
        self.schema_list.clear()
        connection = self.get_connection()
        if connection is None:
            return
        for table, columns in analytics_db.schema_summary(connection):
            self.schema_list.addItem(table)
            for column in columns:
                self.schema_list.addItem(f"    {column}")

    def _reload_saved(self) -> None:
        self.saved_combo.clear()
        for query in analytics_db.load_saved_queries(self.root):
            self.saved_combo.addItem(query["name"], query["sql"])

    def _load_selected(self) -> None:
        sql = self.saved_combo.currentData()
        if sql:
            self.editor.setPlainText(sql)
            self.run_current()

    def _delete_selected(self) -> None:
        name = self.saved_combo.currentText()
        if not name:
            return
        analytics_db.delete_query(self.root, name)
        self.views_changed.emit()
        self._reload_saved()
        self.status.setText(f"Deleted saved view: {name}")

    def run_current(self) -> None:
        sql = self.editor.toPlainText().strip()
        if not sql:
            return
        started = time.perf_counter()
        try:
            columns, rows, truncated = analytics_db.run_query(self.get_connection(), sql)
        except sqlite3.Error as error:
            self.status.setText(f"SQL error: {error}")
            return
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self.results.setColumnCount(len(columns))
        self.results.setHorizontalHeaderLabels(columns)
        self.results.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                self.results.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem("" if value is None else str(value)),
                )
        suffix = " (truncated)" if truncated else ""
        self.status.setText(
            f"{len(rows)} row(s){suffix} in {elapsed_ms:.1f} ms"
        )

    def _save_as_view(self) -> None:
        sql = self.editor.toPlainText().strip()
        if not sql:
            return
        name, accepted = QInputDialog.getText(
            self, "Save as view", "View name:"
        )
        if not accepted or not name.strip():
            return
        analytics_db.save_query(self.root, name.strip(), sql)
        self.views_changed.emit()
        self._reload_saved()
        self.status.setText(f"Saved view: {name.strip()}")
