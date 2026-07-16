from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from phase_tracker import analytics
from phase_tracker.activity_log import ActivityLog


def _seed(log: ActivityLog) -> None:
    log.record("reindex", cancelled=False, file_count=42, nodes=7)
    log.record(
        "local_search", query="parity latch proof", mode="exact",
        result_count=3, duration_ms=12.5, capture_error="",
    )
    log.record(
        "local_search", query="eta shadow readout", mode="broad",
        result_count=0, duration_ms=8.0, capture_error="",
    )
    log.record(
        "external_search", provider="arxiv", query="farey recursion",
        ok=True, result_count=10, total_available=59947, duration_ms=640.0,
    )
    log.record(
        "external_search", provider="semanticscholar", query="critical slowing",
        ok=False, error="rate limit",
    )
    log.record("export_bibtex", provider="arxiv", file="bibtex-arxiv-x.bib", result_count=10)
    log.record("batch", query_count=5, completed=5, exported=5, failed=0, cancelled=False)


class ActivityLogTests(unittest.TestCase):
    def test_append_and_read_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = ActivityLog(root)
            _seed(log)
            events = log.read_events()
            self.assertEqual(len(events), 7)
            self.assertEqual(events[0]["kind"], "reindex")
            self.assertEqual(events[1]["data"]["mode"], "exact")
            self.assertTrue(
                (root / ".project-handoff" / "activity.jsonl").exists()
            )

    def test_malformed_lines_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = ActivityLog(root)
            _seed(log)
            with log.path.open("a", encoding="utf-8") as handle:
                handle.write("not json at all\n")
            log.record("reindex", cancelled=False, file_count=1, nodes=1)
            events = log.read_events()
            self.assertEqual(len(events), 8)

    def test_read_without_ledger_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ActivityLog(Path(tmp)).read_events(), [])


class AnalyticsTests(unittest.TestCase):
    def test_derive_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed(ActivityLog(root))
            metrics = analytics.derive_metrics(root)
            self.assertEqual(metrics["event_count"], 7)
            local = metrics["local_search"]
            self.assertEqual(local["count"], 2)
            self.assertEqual(local["modes"], {"exact": 1, "broad": 1})
            self.assertEqual(local["zero_result_count"], 1)
            self.assertAlmostEqual(local["zero_result_rate"], 0.5)
            arxiv = metrics["external_search"]["arxiv"]
            self.assertEqual(arxiv["ok"], 1)
            self.assertEqual(arxiv["success_rate"], 1.0)
            scholar = metrics["external_search"]["semanticscholar"]
            self.assertEqual(scholar["failed"], 1)
            self.assertEqual(scholar["success_rate"], 0.0)
            self.assertEqual(metrics["export_events"], {"export_bibtex": 1})
            self.assertEqual(metrics["batch"]["queries_executed"], 5)
            self.assertEqual(len(metrics["daily_activity"]), 14)
            self.assertEqual(metrics["daily_activity"][-1][1], 7)
            self.assertEqual(metrics["recent"][0]["kind"], "batch")

    def test_derive_metrics_on_empty_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = analytics.derive_metrics(Path(tmp))
            self.assertEqual(metrics["event_count"], 0)
            self.assertEqual(metrics["local_search"]["count"], 0)
            self.assertEqual(metrics["external_search"], {})
            self.assertEqual(metrics["workflow"]["event_count"], 0)
            rendered = analytics.render_markdown(metrics)
            self.assertIn("no recorded events yet", rendered)

    def test_write_report_schema_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed(ActivityLog(root))
            metrics = analytics.derive_metrics(root)
            json_path, md_path = analytics.write_report(root, metrics)
            self.assertEqual(json_path.parent, root / ".project-handoff" / "reports")
            payload = json.loads(json_path.read_text())
            self.assertEqual(payload["schema_id"], "orchestra.activity-report")
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["metrics"]["event_count"], 7)
            rendered = md_path.read_text()
            self.assertIn("# Orchestra Activity Report", rendered)
            self.assertIn("Semantic Scholar: 1 attempts, 0 ok, 1 failed", rendered)
            self.assertIn("## Daily activity", rendered)

    def _write_workflow_events(self, root: Path) -> None:
        handoff = root / ".project-handoff"
        handoff.mkdir(exist_ok=True)
        records = [
            {"event_type": "coordinate_created", "recorded_at": "2026-07-14T10:00:00+00:00",
             "source_agent": "Operator", "result": "Package produced",
             "coordinate": {"phase": 1, "branch": 1, "version": 1}},
            {"event_type": "current_version_append", "recorded_at": "2026-07-14T11:00:00+00:00",
             "source_agent": "Guardian", "result": "Pass",
             "coordinate": {"phase": 1, "branch": 1, "version": 1}},
            {"event_type": "current_version_append", "recorded_at": "2026-07-14T12:00:00+00:00",
             "source_agent": "Auditor", "result": "Fail",
             "coordinate": {"phase": 1, "branch": 1, "version": 1}},
            {"event_type": "current_version_append", "recorded_at": "2026-07-15T09:00:00+00:00",
             "source_agent": "Auditor", "result": "Pass",
             "coordinate": {"phase": 2, "branch": 1, "version": 1}},
        ]
        with (handoff / "events.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
            handle.write("broken line\n")

    def test_workflow_pass_fail_derivation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_workflow_events(root)
            metrics = analytics.derive_metrics(root)
            workflow = metrics["workflow"]
            self.assertEqual(workflow["event_count"], 4)
            self.assertEqual(
                workflow["by_type"],
                {"coordinate_created": 1, "current_version_append": 3},
            )
            auditor = workflow["agents"]["Auditor"]
            self.assertEqual(auditor["passes"], 1)
            self.assertEqual(auditor["failures"], 1)
            self.assertEqual(auditor["pass_rate"], 0.5)
            operator = workflow["agents"]["Operator"]
            self.assertEqual(operator["passes"], 1)
            self.assertEqual(operator["pass_rate"], 1.0)
            self.assertEqual(
                workflow["per_phase"]["p1"],
                {"Package produced": 1, "Pass": 1, "Fail": 1},
            )
            self.assertFalse(metrics["is_empty"])
            self.assertEqual(metrics["total_recorded"], 4)
            # workflow-only projects still populate the merged feed
            self.assertEqual(metrics["recent"][0]["kind"], "current_version_append")
            self.assertEqual(metrics["recent"][0]["data"]["result"], "Pass")
            rendered = analytics.render_markdown(metrics)
            self.assertIn("## Workflow steps", rendered)
            self.assertIn("Auditor: 2 events", rendered)
            self.assertIn("50.0% pass rate", rendered)

    def test_merged_feed_and_daily_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_workflow_events(root)
            _seed(ActivityLog(root))
            metrics = analytics.derive_metrics(root)
            self.assertEqual(metrics["total_recorded"], 11)
            kinds = {event["kind"] for event in metrics["recent"]}
            self.assertIn("current_version_append", kinds)
            self.assertIn("local_search", kinds)
            from datetime import datetime, timezone

            today = datetime.now(timezone.utc).date().isoformat()
            workflow_today = sum(
                1
                for event in metrics["recent"]
                if event["kind"].startswith(("coordinate_", "current_version"))
                and str(event["ts"]).startswith(today)
            )
            today_count = metrics["daily_activity"][-1][1]
            self.assertEqual(today_count, 7 + workflow_today)

    def test_empty_project_is_flagged_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = analytics.derive_metrics(Path(tmp))
            self.assertTrue(metrics["is_empty"])
            self.assertEqual(metrics["total_recorded"], 0)

    def test_ledger_reads_are_read_only_and_defensive(self) -> None:
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_workflow_events(root)
            handoff = root / ".project-handoff"
            connection = sqlite3.connect(handoff / "workbench.sqlite3")
            connection.execute("CREATE TABLE attachments (destination TEXT)")
            connection.execute("INSERT INTO attachments VALUES ('x')")
            connection.commit()
            connection.close()
            metrics = analytics.derive_metrics(root)
            self.assertEqual(metrics["workflow"]["event_count"], 4)
            self.assertEqual(metrics["workbench_tables"], {"attachments": 1})


class JudgmentMatrixTests(unittest.TestCase):
    def _write_cycle(self, root: Path) -> None:
        handoff = root / ".project-handoff"
        handoff.mkdir(exist_ok=True)
        # Full relay: Op produce -> G pass Op -> Aud pass Op -> G fail Aud ->
        # Aud pass Op (revision) -> G pass Aud -> Op not produced -> Op produce
        # No guardian_subject field: forces historical inference.
        seq = [
            ("Operator", "Package produced"),
            ("Guardian", "Pass"),
            ("Auditor", "Pass"),
            ("Guardian", "Fail"),
            ("Auditor", "Pass"),
            ("Guardian", "Pass"),
            ("Operator", "Not produced"),
            ("Operator", "Package produced"),
        ]
        with (handoff / "events.jsonl").open("w", encoding="utf-8") as handle:
            for index, (agent, result) in enumerate(seq):
                handle.write(json.dumps({
                    "event_type": "current_version_append",
                    "recorded_at": f"2026-07-1{index % 5}T0{index}:00:00+00:00",
                    "source_agent": agent,
                    "result": result,
                    "coordinate": {"phase": 1, "branch": 1, "version": 1},
                }) + "\n")

    def test_matrix_inference_and_marginals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_cycle(root)
            workflow = analytics.derive_metrics(root)["workflow"]
            matrix = workflow["judgment_matrix"]
            # Guardian reviewed Operator once (pass), Auditor twice (1 pass 1 fail)
            self.assertEqual(matrix["Guardian->Operator"]["passes"], 1)
            self.assertEqual(matrix["Guardian->Auditor"]["failures"], 1)
            self.assertEqual(matrix["Guardian->Auditor"]["passes"], 1)
            self.assertNotIn("Guardian->unattributed", matrix)
            # Auditor judged Operator twice, both passes
            self.assertEqual(matrix["Auditor->Operator"]["passes"], 2)
            # Operator self: 2 produced, 1 not
            self.assertEqual(matrix["Operator->Operator"]["passes"], 2)
            self.assertEqual(matrix["Operator->Operator"]["failures"], 1)

            granted = workflow["granted"]
            self.assertEqual(granted["Guardian"]["overall"]["judged_total"], 3)
            self.assertAlmostEqual(granted["Guardian"]["overall"]["pass_rate"], 0.667)
            self.assertEqual(granted["Auditor"]["Operator"]["pass_rate"], 1.0)

            received = workflow["received"]
            op = received["Operator"]
            self.assertEqual(op["Guardian"]["judged_total"], 1)
            self.assertEqual(op["Auditor"]["passes"], 2)
            # overall received by Operator: self 2/3 + guardian 1/1 + auditor 2/2 = 5/6
            self.assertEqual(op["overall"]["judged_total"], 6)
            self.assertAlmostEqual(op["overall"]["pass_rate"], 0.833)
            aud = received["Auditor"]
            self.assertEqual(aud["Guardian"]["judged_total"], 2)
            self.assertAlmostEqual(aud["overall"]["pass_rate"], 0.5)

    def test_explicit_subject_overrides_inference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / ".project-handoff"
            handoff.mkdir()
            records = [
                {"event_type": "current_version_append",
                 "recorded_at": "2026-07-14T10:00:00+00:00",
                 "source_agent": "Guardian", "result": "Fail",
                 "guardian_subject": "Auditor",
                 "coordinate": {"phase": 1, "branch": 1, "version": 1}},
            ]
            with (handoff / "events.jsonl").open("w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record) + "\n")
            workflow = analytics.derive_metrics(root)["workflow"]
            self.assertEqual(
                workflow["judgment_matrix"]["Guardian->Auditor"]["failures"], 1
            )

    def test_alignment_breaks_inference_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / ".project-handoff"
            handoff.mkdir()
            records = [
                {"event_type": "current_version_append",
                 "recorded_at": "2026-07-14T10:00:00+00:00",
                 "source_agent": "Operator", "result": "Package produced",
                 "coordinate": {"phase": 1, "branch": 1, "version": 1}},
                {"event_type": "manual_workflow_alignment",
                 "recorded_at": "2026-07-14T11:00:00+00:00"},
                {"event_type": "current_version_append",
                 "recorded_at": "2026-07-14T12:00:00+00:00",
                 "source_agent": "Guardian", "result": "Pass",
                 "coordinate": {"phase": 1, "branch": 1, "version": 1}},
            ]
            with (handoff / "events.jsonl").open("w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record) + "\n")
            workflow = analytics.derive_metrics(root)["workflow"]
            self.assertEqual(
                workflow["unattributed_guardian_reviews"]["passes"], 1
            )
            self.assertNotIn("Guardian->Operator", workflow["judgment_matrix"])
