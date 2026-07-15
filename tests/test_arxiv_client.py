from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import phase_tracker
from phase_tracker.arxiv_client import build_request_url, parse_feed
from phase_tracker.references import from_arxiv
from phase_tracker.search import reference_exporter

CANNED_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>2</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v2</id>
    <title>Farey Recursion and
       Partition Structure</title>
    <summary>We study a recursion over
       Farey mediants.</summary>
    <published>2024-01-01T00:00:00Z</published>
    <updated>2024-02-01T00:00:00Z</updated>
    <author><name>A. Author</name></author>
    <author><name>B. Author</name></author>
    <arxiv:comment>18 pages, 3 figures</arxiv:comment>
    <arxiv:doi>10.0000/example.doi</arxiv:doi>
    <arxiv:primary_category term="math.NT"/>
    <category term="math.NT"/>
    <category term="math-ph"/>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/2401.00001v2"/>
    <link title="pdf" href="http://arxiv.org/pdf/2401.00001v2"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.00002v1</id>
    <title>Second Entry</title>
    <summary>Second summary.</summary>
    <published>2024-02-02T00:00:00Z</published>
    <updated>2024-02-02T00:00:00Z</updated>
    <author><name>C. Author</name></author>
    <category term="nlin.AO"/>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/2402.00002v1"/>
  </entry>
</feed>
"""


class ArxivClientTests(unittest.TestCase):
    def test_build_request_url_preserves_quoted_phrases(self) -> None:
        url = build_request_url('"farey recursion" partition')
        self.assertIn("export.arxiv.org/api/query", url)
        self.assertIn("all%3A%22farey+recursion%22+partition", url)

    def test_build_request_url_rejects_empty_query(self) -> None:
        with self.assertRaises(ValueError):
            build_request_url("   ")

    def test_build_request_url_caps_max_results(self) -> None:
        self.assertIn("max_results=100", build_request_url("q", max_results=5000))
        self.assertIn("max_results=1", build_request_url("q", max_results=0))

    def test_parse_feed_extracts_results(self) -> None:
        outcome = parse_feed(CANNED_FEED, "farey")
        self.assertEqual(outcome.total_available, 2)
        self.assertEqual(len(outcome.results), 2)
        first = outcome.results[0]
        self.assertEqual(first.arxiv_id, "2401.00001v2")
        self.assertEqual(first.title, "Farey Recursion and Partition Structure")
        self.assertEqual(first.summary, "We study a recursion over Farey mediants.")
        self.assertEqual(first.authors, ("A. Author", "B. Author"))
        self.assertEqual(first.categories, ("math.NT", "math-ph"))
        self.assertEqual(first.primary_category, "math.NT")
        self.assertEqual(first.pdf_url, "http://arxiv.org/pdf/2401.00001v2")
        self.assertEqual(first.doi, "10.0000/example.doi")
        second = outcome.results[1]
        self.assertEqual(second.primary_category, "nlin.AO")
        self.assertEqual(second.pdf_url, "")

    def test_parse_feed_rejects_malformed_xml(self) -> None:
        from phase_tracker.arxiv_client import ArxivClientError

        with self.assertRaises(ArxivClientError):
            parse_feed("<feed>not closed", "q")


class ArxivExporterTests(unittest.TestCase):
    def test_capture_and_write_round_trip(self) -> None:
        outcome = from_arxiv(parse_feed(CANNED_FEED, "farey recursion"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captured = reference_exporter.capture(outcome, search_duration_ms=123.456)
            receipt = reference_exporter.write(root, captured)
            self.assertTrue(receipt.path.exists())
            self.assertTrue(receipt.path.name.startswith("arxiv-"))
            payload = json.loads(receipt.path.read_text())
            self.assertEqual(payload["schema_id"], "orchestra.arxiv-results-export")
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["application"]["version"], phase_tracker.__version__)
            self.assertFalse(payload["source"]["authoritative"])
            self.assertEqual(payload["totals"]["result_count"], 2)
            self.assertEqual(payload["results"][0]["ref_id"], "2401.00001v2")
            self.assertEqual(
                payload["results"][0]["extra"]["primary_category"], "math.NT"
            )
            self.assertEqual(payload["query"]["total_available"], 2)

    def test_exports_land_inside_project_handoff(self) -> None:
        outcome = from_arxiv(parse_feed(CANNED_FEED, "farey"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captured = reference_exporter.capture(outcome, search_duration_ms=1.0)
            receipt = reference_exporter.write(root, captured)
            self.assertEqual(
                receipt.path.parent,
                root / ".project-handoff" / "search-exports",
            )
