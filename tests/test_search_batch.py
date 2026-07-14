from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from phase_tracker.search import export_batch_queries, split_batch_queries
from phase_tracker.search_engine import ProjectSearchIndex


class BatchQueryParserTests(unittest.TestCase):
    def test_multiline_input_preserves_ordinary_commas(self) -> None:
        self.assertEqual(
            split_batch_queries(
                'first query, second clause\n"Guardian rejected, the audit"\r\nthird'
            ),
            [
                "first query, second clause",
                '"Guardian rejected, the audit"',
                "third",
            ],
        )

    def test_single_line_commas_split_queries_outside_quotes(self) -> None:
        self.assertEqual(
            split_batch_queries(
                'first query, second query, "Guardian rejected, the audit"'
            ),
            [
                "first query",
                "second query",
                '"Guardian rejected, the audit"',
            ],
        )

    def test_empty_entries_are_ignored_and_order_is_preserved(self) -> None:
        self.assertEqual(
            split_batch_queries(" alpha\n\nbeta\nalpha \n"),
            ["alpha", "beta", "alpha"],
        )

    def test_unclosed_quote_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "closing double quote"):
            split_batch_queries('first\n"unfinished phrase')


class BatchQueryExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        version = self.root / "p5" / "p5-b3" / "p5-b3-v10"
        version.mkdir(parents=True)
        (version / "proof.md").write_text(
            "The Guardian rejected the spectral parity proof because its bridge was missing.",
            encoding="utf-8",
        )
        (version / "notes.md").write_text(
            "Independent construction notes.",
            encoding="utf-8",
        )
        self.index = ProjectSearchIndex(self.root)
        self.index.rebuild()

    def test_batch_exports_each_query_with_shared_batch_metadata(self) -> None:
        state_path = self.root / ".project-handoff" / "state.json"
        state_path.write_text('{"active_agent":"Auditor"}\n', encoding="utf-8")
        state_before = state_path.read_bytes()
        progress: list[tuple[int, int, str]] = []
        queries = [
            '"Guardian rejected the spectral parity"',
            "independent construction",
            "unfindable cerulean zephyr",
        ]

        report = export_batch_queries(
            self.index,
            queries,
            progress=lambda position, total, query: progress.append(
                (position, total, query)
            ),
        )

        self.assertFalse(report.cancelled)
        self.assertEqual(report.query_count, 3)
        self.assertEqual(report.completed_query_count, 3)
        self.assertEqual(len(report.receipts), 3)
        self.assertEqual(report.failures, ())
        self.assertEqual([item[0] for item in progress], [1, 2, 3])
        self.assertEqual(state_path.read_bytes(), state_before)

        payloads = [
            json.loads(receipt.path.read_text(encoding="utf-8"))
            for receipt in report.receipts
        ]
        self.assertEqual(
            {payload["batch"]["batch_execution_id"] for payload in payloads},
            {report.batch_execution_id},
        )
        self.assertEqual(
            [payload["batch"]["position"] for payload in payloads],
            [1, 2, 3],
        )
        self.assertEqual(
            [payload["batch"]["query_count"] for payload in payloads],
            [3, 3, 3],
        )
        self.assertEqual(payloads[0]["query"]["match_mode"], "quoted_phrase")
        self.assertEqual(payloads[2]["query"]["returned_count"], 0)

    def test_cancellation_stops_before_the_next_query(self) -> None:
        completed: list[int] = []
        report = export_batch_queries(
            self.index,
            ["guardian", "construction", "zephyr"],
            progress=lambda position, _total, _query: completed.append(position),
            cancelled=lambda: bool(completed),
        )

        self.assertTrue(report.cancelled)
        self.assertEqual(report.completed_query_count, 1)
        self.assertEqual(len(report.receipts), 1)
        self.assertEqual(completed, [1])

    def test_twenty_queries_receive_twenty_unique_exports(self) -> None:
        report = export_batch_queries(self.index, ["guardian"] * 20)

        self.assertEqual(report.query_count, 20)
        self.assertEqual(len(report.receipts), 20)
        self.assertEqual(
            len({receipt.path for receipt in report.receipts}),
            20,
        )


if __name__ == "__main__":
    unittest.main()
