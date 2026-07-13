from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from phase_tracker.search import SearchResultsExporter
from phase_tracker.search_engine import ProjectSearchIndex


class SearchExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.version = self.root / "p5" / "p5-b3" / "p5-b3-v10"
        self.version.mkdir(parents=True)
        (self.version / "proof.md").write_text(
            "The Guardian rejected the spectral parity fulcrum because its bridge was missing.",
            encoding="utf-8",
        )
        (self.version / "response.txt").write_text(
            "Revise and resubmit the proof.",
            encoding="utf-8",
        )
        (self.version / "notes.txt").write_text(
            "Independent construction notes.",
            encoding="utf-8",
        )
        with zipfile.ZipFile(self.version / "package.zip", "w") as archive:
            archive.writestr("README.md", "Archived package evidence")
        self.index = ProjectSearchIndex(self.root)
        self.index.rebuild()

    def test_capture_includes_ranked_and_related_metadata(self) -> None:
        results = self.index.search("spectral fulcrum")
        self.assertEqual(len(results), 1)
        captured = SearchResultsExporter(self.index).capture(
            "spectral fulcrum",
            results,
            result_limit=40,
            related_limit=2,
            search_duration_ms=12.34567,
        )

        self.assertEqual(captured["schema_id"], "orchestra.search-results-export")
        self.assertEqual(captured["schema_version"], 2)
        self.assertTrue(str(captured["query_execution_id"]).startswith("sq_"))
        self.assertTrue(str(captured["captured_at"]).endswith("Z"))
        self.assertIsNone(captured["exported_at"])
        self.assertEqual(captured["application"]["version"], "0.2.5")
        self.assertEqual(captured["project"]["root"], str(self.root))
        self.assertEqual(captured["query"]["normalized_terms"], [
            "spectral",
            "fulcrum",
        ])
        self.assertEqual(captured["query"]["match_mode"], "broad_terms")
        self.assertEqual(captured["query"]["quoted_phrases"], [])
        self.assertEqual(captured["query"]["search_duration_ms"], 12.346)
        self.assertFalse(captured["query"]["result_limit_reached"])
        self.assertEqual(captured["index_snapshot"]["file_node_count"], 4)

        match = captured["ranked_matches"][0]
        self.assertEqual(match["position"], 1)
        self.assertTrue(match["score"]["lower_is_better"])
        self.assertEqual(match["node"]["path"], "p5/p5-b3/p5-b3-v10/proof.md")
        self.assertEqual(match["node"]["coordinate"], {
            "phase": 5,
            "branch": 3,
            "version": 10,
        })
        self.assertTrue(match["node"]["exists_at_capture"])
        self.assertNotIn("<mark>", match["snippet"])
        self.assertIn("<mark>", match["snippet_with_match_markers"])

        related = match["same_archived_interaction"]
        self.assertEqual(related["returned_count"], 2)
        self.assertTrue(related["truncated"])
        self.assertEqual(len(related["files"]), 2)
        self.assertEqual(captured["summary"]["related_file_memberships"], 2)

    def test_capture_records_quoted_and_mixed_query_semantics(self) -> None:
        query = '"Guardian rejected the spectral parity" bridge'
        results = self.index.search(query)
        captured = SearchResultsExporter(self.index).capture(query, results)

        self.assertEqual(captured["query"]["match_mode"], "mixed")
        self.assertEqual(captured["query"]["normalized_terms"], ["bridge"])
        self.assertEqual(captured["query"]["quoted_phrases"], [{
            "raw": "Guardian rejected the spectral parity",
            "normalized": "guardian rejected the spectral parity",
            "tokens": ["guardian", "rejected", "the", "spectral", "parity"],
        }])
        self.assertEqual(
            captured["query"]["matching_semantics"]["quoted_phrases"],
            "all_required_as_case_insensitive_adjacent_token_sequences",
        )
        self.assertTrue(captured["ranking"]["quoted_phrase_post_filter"])

    def test_write_is_atomic_unique_and_excluded_from_index(self) -> None:
        state_path = self.root / ".project-handoff" / "state.json"
        state_path.write_text('{"active_agent":"Auditor"}\n', encoding="utf-8")
        state_before = state_path.read_bytes()
        results = self.index.search("spectral fulcrum")
        exporter = SearchResultsExporter(self.index)
        captured = exporter.capture("Spectral fulcrum?!", results)
        first = exporter.write(captured)
        second = exporter.write(captured)

        self.assertNotEqual(first.export_id, second.export_id)
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(
            first.path.parent,
            self.root / ".project-handoff" / "search-exports",
        )
        self.assertTrue(first.path.name.startswith("search-"))
        payload = json.loads(first.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["export_id"], first.export_id)
        self.assertTrue(payload["exported_at"].endswith("Z"))
        self.assertEqual(
            payload["query_execution_id"],
            captured["query_execution_id"],
        )
        self.assertIsNone(captured["exported_at"])
        self.assertNotIn("export_id", captured)
        self.assertEqual(list(first.path.parent.glob(".*.tmp")), [])
        self.assertEqual(state_path.read_bytes(), state_before)

        self.index.rebuild()
        self.assertEqual(self.index.search("orchestra search results export"), [])

    def test_zero_match_query_can_be_exported(self) -> None:
        exporter = SearchResultsExporter(self.index)
        captured = exporter.capture("unfindable cerulean zephyr", [])
        receipt = exporter.write(captured)
        payload = json.loads(receipt.path.read_text(encoding="utf-8"))
        self.assertEqual(receipt.ranked_match_count, 0)
        self.assertEqual(payload["query"]["returned_count"], 0)
        self.assertEqual(payload["ranked_matches"], [])


if __name__ == "__main__":
    unittest.main()
