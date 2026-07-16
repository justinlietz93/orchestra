from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from phase_tracker import analytics_db
from phase_tracker.activity_log import ActivityLog


def _write_ledgers(root: Path) -> None:
    handoff = root / ".project-handoff"
    handoff.mkdir(exist_ok=True)
    seq = [
        ("Operator", "Package produced"),
        ("Guardian", "Pass"),
        ("Auditor", "Fail"),
        ("Guardian", "Fail"),
        ("Auditor", "Pass"),
        ("Guardian", "Pass"),
    ]
    with (handoff / "events.jsonl").open("w", encoding="utf-8") as handle:
        for index, (agent, result) in enumerate(seq):
            handle.write(json.dumps({
                "event_type": "current_version_append",
                "recorded_at": f"2026-07-14T0{index}:00:00+00:00",
                "source_agent": agent,
                "result": result,
                "coordinate": {"phase": 1, "branch": 1, "version": 1},
            }) + "\n")
    log = ActivityLog(root)
    log.record("local_search", query="parity", mode="exact",
               result_count=2, duration_ms=3.0)
    log.record("external_search", provider="arxiv", query="farey",
               ok=True, result_count=5, total_available=100, duration_ms=200.0)
    connection = sqlite3.connect(handoff / "workbench.sqlite3")
    connection.execute("CREATE TABLE attachments (destination TEXT)")
    connection.execute("INSERT INTO attachments VALUES ('phase-1/user-research/a')")
    connection.commit()
    connection.close()


class AnalyticsDbTests(unittest.TestCase):
    def test_read_model_tables_and_judgments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ledgers(root)
            connection = analytics_db.build_database(root)
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM workflow_events"
                ).fetchone()[0]
                self.assertEqual(count, 6)
                rows = connection.execute(
                    "SELECT judge, judged, SUM(is_pass), SUM(is_fail) "
                    "FROM judgments GROUP BY judge, judged ORDER BY judge"
                ).fetchall()
                as_dict = {(r[0], r[1]): (r[2], r[3]) for r in rows}
                self.assertEqual(as_dict[("Auditor", "Operator")], (1, 1))
                self.assertEqual(as_dict[("Guardian", "Auditor")], (1, 1))
                self.assertEqual(as_dict[("Guardian", "Operator")], (1, 0))
                activity = connection.execute(
                    "SELECT kind, provider, ok FROM activity ORDER BY sequence"
                ).fetchall()
                self.assertEqual(activity[1]["provider"], "arxiv")
                self.assertEqual(activity[1]["ok"], 1)
                workbench = connection.execute(
                    "SELECT COUNT(*) FROM workbench.attachments"
                ).fetchone()[0]
                self.assertEqual(workbench, 1)
            finally:
                connection.close()

    def test_connection_is_query_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ledgers(root)
            connection = analytics_db.build_database(root)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("INSERT INTO activity (sequence) VALUES (999)")
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("DROP TABLE judgments")
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute(
                        "INSERT INTO workbench.attachments VALUES ('x')"
                    )
            finally:
                connection.close()

    def test_run_query_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ledgers(root)
            connection = analytics_db.build_database(root)
            try:
                columns, rows, truncated = analytics_db.run_query(
                    connection, "SELECT * FROM judgments", max_rows=2
                )
                self.assertEqual(len(rows), 2)
                self.assertTrue(truncated)
                self.assertIn("judge", columns)
            finally:
                connection.close()

    def test_saved_queries_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".project-handoff").mkdir()
            analytics_db.save_query(root, "pass rates", "SELECT 1")
            analytics_db.save_query(root, "volumes", "SELECT 2")
            analytics_db.save_query(root, "pass rates", "SELECT 3")  # replace
            queries = analytics_db.load_saved_queries(root)
            self.assertEqual(len(queries), 2)
            by_name = {q["name"]: q["sql"] for q in queries}
            self.assertEqual(by_name["pass rates"], "SELECT 3")
            analytics_db.delete_query(root, "volumes")
            self.assertEqual(
                [q["name"] for q in analytics_db.load_saved_queries(root)],
                ["pass rates"],
            )

    def test_empty_project_builds_empty_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            connection = analytics_db.build_database(Path(tmp))
            try:
                for table in ("workflow_events", "judgments", "activity", "export_files"):
                    count = connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                    self.assertEqual(count, 0)
            finally:
                connection.close()
