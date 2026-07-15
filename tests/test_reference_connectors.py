from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from phase_tracker import crossref_client, pubmed_client, semantic_scholar_client
from phase_tracker.search import reference_exporter

CROSSREF_PAYLOAD = json.dumps(
    {
        "message": {
            "total-results": 4321,
            "items": [
                {
                    "DOI": "10.1000/jnt.2024.001",
                    "title": ["Farey Mediants in  Partition Theory"],
                    "author": [
                        {"given": "Ada", "family": "Lovelace"},
                        {"name": "The Structures Consortium"},
                    ],
                    "abstract": "<jats:p>We prove a <jats:i>mediant</jats:i> bound.</jats:p>",
                    "container-title": ["Journal of Number Theory"],
                    "issued": {"date-parts": [[2024, 7, 15]]},
                    "URL": "https://doi.org/10.1000/jnt.2024.001",
                    "type": "journal-article",
                    "volume": "12",
                    "issue": "3",
                    "page": "1-20",
                    "publisher": "Example Press",
                    "link": [
                        {
                            "URL": "https://example.org/paper.pdf",
                            "content-type": "application/pdf",
                        }
                    ],
                }
            ],
        }
    }
)

PUBMED_ESEARCH = json.dumps(
    {"esearchresult": {"count": "77", "idlist": ["12345678"]}}
)

PUBMED_EFETCH = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <Journal>
          <JournalIssue>
            <Volume>42</Volume>
            <Issue>7</Issue>
            <PubDate><Year>2023</Year><Month>Jul</Month></PubDate>
          </JournalIssue>
          <Title>Nature Neuroscience</Title>
        </Journal>
        <ArticleTitle>Neuronal avalanches follow a power law.</ArticleTitle>
        <Pagination><MedlinePgn>101-110</MedlinePgn></Pagination>
        <Abstract>
          <AbstractText Label="BACKGROUND">Avalanches occur.</AbstractText>
          <AbstractText Label="RESULTS">Power laws hold.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Beggs</LastName><ForeName>John</ForeName></Author>
          <Author><CollectiveName>The Criticality Group</CollectiveName></Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">12345678</ArticleId>
        <ArticleId IdType="doi">10.1038/nn.example</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

SEMANTIC_SCHOLAR_PAYLOAD = json.dumps(
    {
        "total": 9001,
        "data": [
            {
                "paperId": "abc123",
                "title": "Critical Slowing Down in  Cognitive Systems",
                "abstract": "We measure early warnings.",
                "authors": [{"name": "Emmy Noether"}],
                "year": 2022,
                "venue": "Physical Review E",
                "externalIds": {"DOI": "10.1103/pre.example", "ArXiv": "2201.00001"},
                "url": "https://www.semanticscholar.org/paper/abc123",
                "openAccessPdf": {"url": "https://example.org/oa.pdf"},
                "publicationDate": "2022-03-04",
                "citationCount": 57,
                "influentialCitationCount": 9,
                "publicationTypes": ["JournalArticle"],
            }
        ],
    }
)


class CrossrefParserTests(unittest.TestCase):
    def test_parse_payload(self) -> None:
        outcome = crossref_client.parse_payload(CROSSREF_PAYLOAD, "farey mediants")
        self.assertEqual(outcome.provider, "crossref")
        self.assertEqual(outcome.total_available, 4321)
        reference = outcome.references[0]
        self.assertEqual(reference.doi, "10.1000/jnt.2024.001")
        self.assertEqual(reference.title, "Farey Mediants in Partition Theory")
        self.assertEqual(
            reference.authors, ("Ada Lovelace", "The Structures Consortium")
        )
        self.assertEqual(reference.summary, "We prove a mediant bound.")
        self.assertEqual(reference.venue, "Journal of Number Theory")
        self.assertEqual(reference.published, "2024-07-15")
        self.assertEqual(reference.pdf_url, "https://example.org/paper.pdf")
        extra = reference.extra_dict()
        self.assertEqual(extra["type"], "journal-article")
        self.assertEqual(extra["pages"], "1-20")

    def test_malformed_payload_raises(self) -> None:
        from phase_tracker.references import ConnectorError

        with self.assertRaises(ConnectorError):
            crossref_client.parse_payload("not json", "q")


class PubmedParserTests(unittest.TestCase):
    def test_parse_esearch(self) -> None:
        pmids, total = pubmed_client.parse_esearch(PUBMED_ESEARCH)
        self.assertEqual(pmids, ["12345678"])
        self.assertEqual(total, 77)

    def test_parse_efetch(self) -> None:
        outcome = pubmed_client.parse_efetch(PUBMED_EFETCH, "avalanches", 77)
        self.assertEqual(outcome.provider, "pubmed")
        self.assertEqual(outcome.total_available, 77)
        reference = outcome.references[0]
        self.assertEqual(reference.ref_id, "12345678")
        self.assertEqual(reference.title, "Neuronal avalanches follow a power law.")
        self.assertEqual(
            reference.summary,
            "BACKGROUND: Avalanches occur. RESULTS: Power laws hold.",
        )
        self.assertEqual(reference.authors, ("John Beggs", "The Criticality Group"))
        self.assertEqual(reference.venue, "Nature Neuroscience")
        self.assertEqual(reference.published, "2023-07")
        self.assertEqual(reference.doi, "10.1038/nn.example")
        self.assertEqual(reference.url, "https://pubmed.ncbi.nlm.nih.gov/12345678/")
        extra = reference.extra_dict()
        self.assertEqual(extra["volume"], "42")
        self.assertEqual(extra["pages"], "101-110")


class SemanticScholarParserTests(unittest.TestCase):
    def test_parse_payload(self) -> None:
        outcome = semantic_scholar_client.parse_payload(
            SEMANTIC_SCHOLAR_PAYLOAD, "critical slowing"
        )
        self.assertEqual(outcome.provider, "semanticscholar")
        self.assertEqual(outcome.total_available, 9001)
        reference = outcome.references[0]
        self.assertEqual(reference.ref_id, "abc123")
        self.assertEqual(
            reference.title, "Critical Slowing Down in Cognitive Systems"
        )
        self.assertEqual(reference.published, "2022-03-04")
        self.assertEqual(reference.pdf_url, "https://example.org/oa.pdf")
        extra = reference.extra_dict()
        self.assertEqual(extra["citations"], "57")
        self.assertEqual(extra["arxiv_id"], "2201.00001")


class UnifiedExporterTests(unittest.TestCase):
    def test_schema_family_per_provider(self) -> None:
        outcome = crossref_client.parse_payload(CROSSREF_PAYLOAD, "farey mediants")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captured = reference_exporter.capture(outcome, search_duration_ms=5.0)
            receipt = reference_exporter.write(root, captured)
            payload = json.loads(receipt.path.read_text())
            self.assertEqual(
                payload["schema_id"], "orchestra.crossref-results-export"
            )
            self.assertEqual(payload["schema_version"], 1)
            self.assertFalse(payload["source"]["authoritative"])
            self.assertTrue(receipt.path.name.startswith("crossref-"))

    def test_bibliography_written_inside_project_handoff(self) -> None:
        outcome = pubmed_client.parse_efetch(PUBMED_EFETCH, "avalanches", 77)
        from phase_tracker.bibtex import format_bibliography

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = format_bibliography(outcome.references, "test header")
            path = reference_exporter.write_bibliography(root, outcome, text)
            self.assertEqual(
                path.parent, root / ".project-handoff" / "search-exports"
            )
            self.assertTrue(path.name.startswith("bibtex-pubmed-"))
            content = path.read_text()
            self.assertIn("@article{pubmed_beggs2023,", content)
            self.assertIn("note = {PMID: 12345678},", content)
