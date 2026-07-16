from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from phase_tracker.activity_log import ActivityLog
from phase_tracker.search_engine import ProjectSearchIndex
from phase_tracker.search_panel import SearchPanel

_app = QApplication.instance() or QApplication([])


class SearchPanelActivityTests(unittest.TestCase):
    """Pins the seam between result rendering and activity recording.

    Regression guard: instrumenting local_search recording must never
    displace per-result registration in results_by_node (all results must
    be registered, and zero-result searches must not raise).
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        phase = self.root / "phase-1"
        phase.mkdir(parents=True)
        (phase / "alpha.md").write_text("parity latch alpha document")
        (phase / "beta.md").write_text("parity latch beta document")
        self.panel = SearchPanel()
        self.panel.set_root(self.root, auto_index=False)
        self.panel.index = ProjectSearchIndex(self.root)
        self.panel.index.rebuild()

    def tearDown(self) -> None:
        self.panel.stop_background_work()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_results_registered_and_search_recorded(self) -> None:
        self.panel.query.setText("parity latch")
        self.panel.run_search()
        self.assertEqual(len(self.panel.results_by_node), 2)
        self.assertEqual(self.panel.results.count(), 2)
        events = ActivityLog(self.root).read_events()
        self.assertEqual(events[-1]["kind"], "local_search")
        self.assertEqual(events[-1]["data"]["result_count"], 2)

    def test_zero_result_search_is_safe_and_recorded(self) -> None:
        self.panel.query.setText("nonexistent zebra term")
        self.panel.run_search()
        self.assertEqual(len(self.panel.results_by_node), 0)
        events = ActivityLog(self.root).read_events()
        self.assertEqual(events[-1]["data"]["result_count"], 0)
