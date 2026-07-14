from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .search import split_batch_queries


class BatchQueryDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Batch search and export")
        self.resize(640, 440)

        layout = QVBoxLayout(self)
        instructions = QLabel(
            "Enter one query per line. A single-line comma-separated list also "
            "works. In multiline input, ordinary commas remain part of their "
            "query. Every query is exported as its own JSON file."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "What failed around parity seating?\n"
            '"Guardian rejected the audit"\n'
            '"lens matrix bridge" auditor'
        )
        self.editor.textChanged.connect(self._update_query_count)
        layout.addWidget(self.editor, 1)

        self.query_count = QLabel("No queries entered")
        self.query_count.setObjectName("muted")
        layout.addWidget(self.query_count)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.run_button = buttons.addButton(
            "Run and export",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.run_button.setObjectName("primary")
        self.run_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def queries(self) -> list[str]:
        return split_batch_queries(self.editor.toPlainText())

    def _update_query_count(self) -> None:
        try:
            queries = self.queries()
        except ValueError as error:
            self.query_count.setText(str(error))
            self.query_count.setStyleSheet("color: #e29a78;")
            self.run_button.setEnabled(False)
            return

        self.query_count.setStyleSheet("")
        count = len(queries)
        if count:
            self.query_count.setText(
                f"{count} quer{'y' if count == 1 else 'ies'} ready to export"
            )
        else:
            self.query_count.setText("No queries entered")
        self.run_button.setEnabled(bool(count))
