"""Analytics dashboard: a full workspace view over the ledgers.

Structured like an activity-bar workspace: a narrow navigation rail on the
left selects exactly one focused section — Overview, Judgments, Providers,
Views, Activity, Query — rendered with full space on the right. Never modal.

Read-only by construction: metrics derive on demand from the ledgers, the
query connection is the disposable in-memory read-model, and closing the
panel changes nothing because the panel holds nothing.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import analytics, analytics_db
from .references import PROVIDER_LABELS

SECTIONS = (
    ("Overview", "\u2302"),
    ("Judgments", "\u2696"),
    ("Providers", "\u2b1a"),
    ("Views", "\u25a4"),
    ("Activity", "\u2630"),
    ("Query", "\u2318"),
)


class DailyActivityChart(QWidget):
    """Minimal bar chart painted directly; no charting dependency."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.days: list[tuple[str, int]] = []
        self.setMinimumHeight(140)

    def set_days(self, days: list[tuple[str, int]]) -> None:
        self.days = days
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.days:
            return
        width = self.width()
        height = self.height()
        label_space = 18
        chart_height = height - label_space
        peak = max((count for _day, count in self.days), default=0) or 1
        slot = width / len(self.days)
        bar_width = max(4, int(slot * 0.6))
        bar_color = QColor(96, 165, 250)
        text_color = QColor(148, 163, 184)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, (day, count) in enumerate(self.days):
            bar_height = int(chart_height * (count / peak)) if count else 2
            x = int(index * slot + (slot - bar_width) / 2)
            y = chart_height - bar_height
            painter.setBrush(bar_color if count else QColor(51, 65, 85))
            painter.drawRoundedRect(x, y, bar_width, bar_height, 2, 2)
        painter.setPen(text_color)
        painter.drawText(2, height - 4, self.days[0][0][5:])
        painter.drawText(width - 42, height - 4, self.days[-1][0][5:])
        painter.drawText(int(width / 2) - 20, height - 4, f"peak {peak}")
        painter.end()


class DonutChart(QWidget):
    """Pass/fail donut painted directly; no charting dependency."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.passes = 0
        self.failures = 0
        self.setMinimumSize(150, 150)

    def set_data(self, passes: int, failures: int) -> None:
        self.passes = passes
        self.failures = failures
        self.update()

    def paintEvent(self, _event) -> None:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QFont, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        thickness = max(12, int(side * 0.11))
        margin = thickness / 2 + 4
        rect = QRectF(
            (self.width() - side) / 2 + margin,
            (self.height() - side) / 2 + margin,
            side - 2 * margin,
            side - 2 * margin,
        )
        total = self.passes + self.failures
        base_pen = QPen(QColor(31, 42, 61), thickness)
        base_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(base_pen)
        painter.drawArc(rect, 0, 360 * 16)
        if total:
            span = int(360 * 16 * (self.passes / total))
            pass_pen = QPen(QColor(52, 211, 153), thickness)
            pass_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pass_pen)
            painter.drawArc(rect, 90 * 16, -span)
            if self.failures:
                fail_pen = QPen(QColor(248, 113, 113), thickness)
                fail_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                painter.setPen(fail_pen)
                painter.drawArc(rect, 90 * 16 - span, -(360 * 16 - span))
        painter.setPen(QColor(230, 238, 250))
        font = QFont(self.font())
        font.setPointSize(max(13, int(side * 0.11)))
        font.setBold(True)
        painter.setFont(font)
        center_text = f"{self.passes / total:.0%}" if total else "–"
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, center_text)
        painter.setPen(QColor(148, 163, 184))
        small = QFont(self.font())
        small.setPointSize(max(8, int(side * 0.055)))
        painter.setFont(small)
        detail_rect = QRectF(rect.x(), rect.y() + rect.height() * 0.62,
                             rect.width(), rect.height() * 0.2)
        detail = f"{self.passes}/{total}" if total else "no verdicts"
        painter.drawText(detail_rect, Qt.AlignmentFlag.AlignCenter, detail)
        painter.end()


def _make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setStretchLastSection(True)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    return table


def _fill(table: QTableWidget, rows: list[tuple]) -> None:
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            table.setItem(
                row_index,
                column_index,
                QTableWidgetItem("" if value is None else str(value)),
            )


def _fmt_cell(cell: dict | None) -> str:
    if not cell or cell["judged_total"] == 0:
        return "–"
    return f"{cell['pass_rate']:.0%} ({cell['passes']}/{cell['judged_total']})"


class AnalyticsView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.root: Path | None = None
        self.connection: sqlite3.Connection | None = None
        self.metrics: dict = {}
        self.query_editor = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.rail = QListWidget()
        self.rail.setFixedWidth(240)
        self.rail.setObjectName("analyticsRail")
        self.rail.setStyleSheet(
            """
            QListWidget#analyticsRail {
                background: #0d1420;
                border: none;
                border-right: 1px solid #1f2a3d;
                outline: none;
                padding-top: 10px;
                font-size: 14px;
            }
            QListWidget#analyticsRail::item {
                height: 40px;
                margin: 2px 8px;
                padding-left: 10px;
                border-radius: 6px;
                color: #93a4bd;
            }
            QListWidget#analyticsRail::item:hover { color: #e2ebf8; }
            QListWidget#analyticsRail::item:selected {
                background: #1d2a44;
                color: #7fb2ff;
                font-weight: 600;
            }
            """
        )
        for name, glyph in SECTIONS:
            self.rail.addItem(QListWidgetItem(f" {glyph}  {name}"))
        self.rail.setCurrentRow(0)
        outer.addWidget(self.rail)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.rail.currentRowChanged.connect(self.stack.setCurrentIndex)

        self.stack.addWidget(self._build_overview())
        self.stack.addWidget(self._build_judgments())
        self.stack.addWidget(self._build_providers())
        self.stack.addWidget(self._build_views())
        self.stack.addWidget(self._build_activity())
        self.query_page = QWidget()
        query_layout = QVBoxLayout(self.query_page)
        self.query_placeholder = QLabel("Open a project to query its ledgers.")
        query_layout.addWidget(self.query_placeholder)
        self.stack.addWidget(self.query_page)

    # ---------- section builders ----------

    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)
        caption = QLabel(subtitle)
        caption.setWordWrap(True)
        layout.addWidget(caption)
        return page, layout

    def _build_overview(self) -> QWidget:
        page, layout = self._page(
            "Overview",
            "Derived on demand from the activity and evidence ledgers. "
            "Read-only: refreshing recomputes, closing changes nothing.",
        )
        self.empty_banner = QLabel(
            "No recorded activity yet. Workflow steps appear here as you archive "
            "handoffs; searches, external queries, and exports are recorded from "
            "the moment this version was installed."
        )
        self.empty_banner.setWordWrap(True)
        self.empty_banner.setStyleSheet("font-weight: 600;")
        self.empty_banner.setVisible(False)
        layout.addWidget(self.empty_banner)

        cards = QGridLayout()
        cards.setVerticalSpacing(2)
        self.card_labels: dict[str, QLabel] = {}
        for column, (key, caption) in enumerate(
            (
                ("workflow", "Workflow steps"),
                ("pass_rate", "Step pass rate"),
                ("local", "Local searches"),
                ("external", "External searches"),
                ("exports", "Export actions"),
            )
        ):
            value = QLabel("–")
            value.setStyleSheet("font-size: 26px; font-weight: 600;")
            cards.addWidget(value, 0, column)
            cards.addWidget(QLabel(caption), 1, column)
            self.card_labels[key] = value
        layout.addLayout(cards)

        layout.addSpacing(10)
        donut_row = QHBoxLayout()
        self.donuts: dict[str, DonutChart] = {}
        for key, caption in (
            ("operator", "Operator — verdicts received"),
            ("guardian", "Guardian — verdicts granted"),
            ("auditor", "Auditor — verdicts received"),
        ):
            column = QVBoxLayout()
            donut = DonutChart()
            self.donuts[key] = donut
            column.addWidget(donut, 1)
            caption_label = QLabel(caption)
            caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(caption_label)
            donut_row.addLayout(column, 1)
        layout.addLayout(donut_row, 2)

        layout.addSpacing(10)
        layout.addWidget(QLabel("Activity per day (last 14 days)"))
        self.chart = DailyActivityChart()
        layout.addWidget(self.chart, 1)
        button_row = QHBoxLayout()
        self.status = QLabel("")
        button_row.addWidget(self.status, 1)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        button_row.addWidget(refresh_button)
        report_button = QPushButton("Export report")
        report_button.setToolTip(
            "Write the derived metrics as JSON + Markdown to "
            ".project-handoff/reports/."
        )
        report_button.clicked.connect(self._export_report)
        button_row.addWidget(report_button)
        layout.addLayout(button_row)
        return page

    def _build_judgments(self) -> QWidget:
        page, layout = self._page(
            "Judgments",
            "Verdict matrix from the workflow journal. Rates read as "
            "pass rate (passes/judged).",
        )
        layout.addWidget(QLabel("Judging — verdicts granted"))
        self.judging_table = _make_table(
            ["Judge", "→ Operator", "→ Auditor", "Overall granted"]
        )
        layout.addWidget(self.judging_table, 1)
        layout.addWidget(QLabel("Judged — verdicts received"))
        self.judged_table = _make_table(
            ["Subject", "By Operator (self)", "By Guardian", "By Auditor",
             "Overall received"]
        )
        layout.addWidget(self.judged_table, 1)
        return page

    def _build_providers(self) -> QWidget:
        page, layout = self._page(
            "Providers",
            "External literature searches: attempts, outcomes, and success "
            "rates per provider.",
        )
        self.provider_table = _make_table(
            ["Provider", "Attempts", "OK", "Failed", "Success rate"]
        )
        layout.addWidget(self.provider_table, 1)
        return page

    def _build_views(self) -> QWidget:
        page, layout = self._page(
            "Views",
            "Saved SQL views, re-run on every refresh. Create them in the "
            "Query section.",
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.saved_views_container = QVBoxLayout(inner)
        self.saved_views_container.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        return page

    def _build_activity(self) -> QWidget:
        page, layout = self._page(
            "Activity",
            "Most recent events, merged from the workflow journal and the "
            "activity ledger.",
        )
        self.feed = QListWidget()
        layout.addWidget(self.feed, 1)
        return page

    # ---------- lifecycle ----------

    def set_root(self, root: Path) -> None:
        self.root = root
        self.refresh()
        if self.query_editor is None:
            from .query_editor import QueryEditorWidget

            self.query_editor = QueryEditorWidget(lambda: self.connection, root)
            self.query_editor.views_changed.connect(self._render_saved_views)
            layout = self.query_page.layout()
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            layout.addWidget(self.query_editor, 1)
        else:
            self.query_editor.root = root
            self.query_editor.reload_schema()

    def refresh(self) -> None:
        if self.root is None:
            return
        if self.connection is not None:
            self.connection.close()
        self.connection = analytics_db.build_database(self.root)
        self.metrics = analytics.derive_metrics(self.root)
        metrics = self.metrics
        local = metrics["local_search"]
        workflow = metrics["workflow"]
        external_attempts = sum(
            stats["attempts"] for stats in metrics["external_search"].values()
        )
        export_actions = sum(metrics["export_events"].values())
        matrix_cells = workflow["judgment_matrix"].values()
        total_passes = sum(cell["passes"] for cell in matrix_cells)
        total_failures = sum(cell["failures"] for cell in matrix_cells)
        judged = total_passes + total_failures
        self.card_labels["workflow"].setText(str(workflow["event_count"]))
        self.card_labels["pass_rate"].setText(
            f"{total_passes / judged:.0%}" if judged else "–"
        )
        self.card_labels["local"].setText(str(local["count"]))
        self.card_labels["external"].setText(str(external_attempts))
        self.card_labels["exports"].setText(str(export_actions))
        self.empty_banner.setVisible(bool(metrics.get("is_empty")))
        self.chart.set_days(metrics["daily_activity"])
        received = workflow["received"]
        granted = workflow["granted"]
        for key, cell in (
            ("operator", received["Operator"]["overall"]),
            ("guardian", granted["Guardian"]["overall"]),
            ("auditor", received["Auditor"]["overall"]),
        ):
            self.donuts[key].set_data(cell["passes"], cell["failures"])

        _fill(
            self.judging_table,
            [
                ("Operator", _fmt_cell(granted["Operator"]["Operator"]), "–",
                 _fmt_cell(granted["Operator"]["overall"])),
                ("Guardian", _fmt_cell(granted["Guardian"]["Operator"]),
                 _fmt_cell(granted["Guardian"]["Auditor"]),
                 _fmt_cell(granted["Guardian"]["overall"])),
                ("Auditor", _fmt_cell(granted["Auditor"]["Operator"]), "–",
                 _fmt_cell(granted["Auditor"]["overall"])),
            ],
        )
        _fill(
            self.judged_table,
            [
                ("Operator", _fmt_cell(received["Operator"]["Operator"]),
                 _fmt_cell(received["Operator"]["Guardian"]),
                 _fmt_cell(received["Operator"]["Auditor"]),
                 _fmt_cell(received["Operator"]["overall"])),
                ("Auditor", "–", _fmt_cell(received["Auditor"]["Guardian"]),
                 "–", _fmt_cell(received["Auditor"]["overall"])),
            ],
        )
        _fill(
            self.provider_table,
            [
                (
                    PROVIDER_LABELS.get(provider, provider),
                    str(stats["attempts"]),
                    str(stats["ok"]),
                    str(stats["failed"]),
                    f"{stats['success_rate']:.0%}",
                )
                for provider, stats in sorted(metrics["external_search"].items())
            ],
        )

        self.feed.clear()
        for event in metrics["recent"]:
            data = event["data"]
            detail_bits = []
            for key in (
                "agent", "result", "coordinate", "query", "provider",
                "mode", "result_count", "file_count", "error",
            ):
                if key in data and data[key] not in ("", None):
                    detail_bits.append(f"{key}={data[key]}")
            timestamp = str(event["ts"]).replace("T", " ")[:19]
            self.feed.addItem(f"{timestamp}  {event['kind']}  " + "  ".join(detail_bits))

        self._render_saved_views()
        self.status.setText(
            f"Derived at {metrics['generated_at'][:19].replace('T', ' ')} UTC"
        )

    def _render_saved_views(self) -> None:
        while self.saved_views_container.count() > 1:
            item = self.saved_views_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self.root is None or self.connection is None:
            return
        queries = analytics_db.load_saved_queries(self.root)
        insert_at = 0
        if not queries:
            placeholder = QLabel(
                "No saved views yet. Save a query in the Query section and it "
                "renders here."
            )
            self.saved_views_container.insertWidget(insert_at, placeholder)
            return
        for query in queries:
            caption = QLabel(query["name"])
            caption.setStyleSheet("font-weight: 600;")
            self.saved_views_container.insertWidget(insert_at, caption)
            insert_at += 1
            try:
                columns, rows, truncated = analytics_db.run_query(
                    self.connection, query["sql"]
                )
            except sqlite3.Error as error:
                caption.setText(f"{query['name']} — SQL error: {error}")
                continue
            table = _make_table(columns)
            table.setMinimumHeight(120)
            _fill(table, rows)
            if truncated:
                caption.setText(
                    f"{query['name']} (first {analytics_db.MAX_VIEW_ROWS} rows)"
                )
            self.saved_views_container.insertWidget(insert_at, table)
            insert_at += 1

    def close_connection(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _export_report(self) -> None:
        json_path, md_path = analytics.write_report(self.root, self.metrics)
        self.status.setText(f"Report written: {json_path.name} and {md_path.name}")
