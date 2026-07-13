import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from phase_tracker.search_engine import ProjectSearchIndex, query_terms
from phase_tracker.search_query import parse_search_query


class SearchEngineTests(unittest.TestCase):
    def test_natural_language_terms_remove_query_scaffolding(self) -> None:
        self.assertEqual(
            query_terms("What did the Guardian reject about parity seating?"),
            ["guardian", "reject", "parity", "seating"],
        )

    def test_quoted_query_is_parsed_separately_from_broad_terms(self) -> None:
        parsed = parse_search_query(
            'show "Guardian rejected the audit" around parity'
        )

        self.assertEqual(parsed.match_mode, "mixed")
        self.assertEqual(parsed.terms, ("around", "parity"))
        self.assertEqual(len(parsed.quoted_phrases), 1)
        self.assertEqual(
            parsed.quoted_phrases[0].tokens,
            ("guardian", "rejected", "the", "audit"),
        )
        self.assertEqual(
            parsed.fts_expression,
            '("guardian rejected the audit") AND ("around"* OR "parity"*)',
        )

    def test_quoted_phrase_requires_exact_words_together_and_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("exact.md").write_text(
                "The GUARDIAN,\nrejected -- the audit after review.",
                encoding="utf-8",
            )
            root.joinpath("interrupted.md").write_text(
                "The Guardian firmly rejected the audit.",
                encoding="utf-8",
            )
            root.joinpath("stem-only.md").write_text(
                "The Guardian rejects the audit.",
                encoding="utf-8",
            )
            root.joinpath("reversed.md").write_text(
                "The audit rejected the Guardian.",
                encoding="utf-8",
            )

            index = ProjectSearchIndex(root)
            index.rebuild()

            quoted = index.search('"guardian rejected the audit"')
            self.assertEqual([result.name for result in quoted], ["exact.md"])

            broad = index.search("guardian audit")
            self.assertEqual(
                {result.name for result in broad},
                {"exact.md", "interrupted.md", "stem-only.md", "reversed.md"},
            )

    def test_mixed_query_requires_phrase_and_at_least_one_broad_term(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("with-bridge.md").write_text(
                "The Guardian rejected the audit because the bridge was absent.",
                encoding="utf-8",
            )
            root.joinpath("without-extra.md").write_text(
                "The Guardian rejected the audit because evidence was absent.",
                encoding="utf-8",
            )
            root.joinpath("bridge-only.md").write_text(
                "The bridge was discussed without a rejection.",
                encoding="utf-8",
            )

            index = ProjectSearchIndex(root)
            index.rebuild()
            results = index.search('"guardian rejected the audit" bridge')

            self.assertEqual([result.name for result in results], ["with-bridge.md"])

    def test_index_search_and_same_version_relations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version = root / "Phase-5_Prime_QBL" / "p5-b3" / "p5-b3-v10"
            version.mkdir(parents=True)
            proof = version / "parity-proof.md"
            proof.write_text(
                "The Guardian rejected parity seating because the lens matrix bridge was missing.",
                encoding="utf-8",
            )
            response = version / "p5-b3-v10-response.txt"
            response.write_text("Revise and resubmit the proof.", encoding="utf-8")
            notebook = version / "check.ipynb"
            notebook.write_text(
                json.dumps({"cells": [{"source": ["signed positions and parity latch"], "outputs": []}]}),
                encoding="utf-8",
            )
            package = version / "package.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("docs/FINDINGS.md", "affine symbolic language boundary")

            index = ProjectSearchIndex(root)
            summary = index.rebuild()
            results = index.search("What did the Guardian reject about parity seating?")

            self.assertEqual(summary["indexed_files"], 4)
            self.assertTrue(results)
            self.assertTrue(results[0].path.endswith("parity-proof.md"))
            self.assertEqual(results[0].phase, 5)
            self.assertEqual(results[0].branch, 3)
            self.assertEqual(results[0].version, 10)

            related_names = {item.name for item in index.related_files(results[0].node_id)}
            self.assertIn("p5-b3-v10-response.txt", related_names)
            self.assertIn("package.zip", related_names)
            self.assertEqual(index.search("affine symbolic boundary")[0].name, "package.zip")


if __name__ == "__main__":
    unittest.main()
