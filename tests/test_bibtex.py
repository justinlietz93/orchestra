from __future__ import annotations

import unittest

from phase_tracker.bibtex import (
    entry_type,
    format_bibliography,
    format_entry,
    generate_cite_key,
)
from phase_tracker.references import ExternalReference


def _reference(**overrides) -> ExternalReference:
    base = dict(
        provider="arxiv",
        ref_id="2401.00001v2",
        title="Farey Recursion & Partition Structure",
        authors=("Ada Lovelace", "Emmy Noether"),
        summary="A summary.",
        venue="math.NT",
        published="2024-07-01T00:00:00Z",
        url="https://arxiv.org/abs/2401.00001v2",
        doi="10.0000/example",
        extra=(("primary_category", "math.NT"),),
    )
    base.update(overrides)
    return ExternalReference(**base)


class BibtexTests(unittest.TestCase):
    def test_arxiv_preprint_is_misc_with_eprint_fields(self) -> None:
        entry = format_entry(_reference())
        self.assertTrue(entry.startswith("@misc{arxiv_lovelace2024,"))
        self.assertIn("eprint = {2401.00001v2},", entry)
        self.assertIn("archivePrefix = {arXiv},", entry)
        self.assertIn("primaryClass = {math.NT},", entry)
        self.assertIn("author = {Ada Lovelace and Emmy Noether},", entry)
        self.assertIn("month = jul,", entry)
        self.assertIn("doi = {10.0000/example},", entry)

    def test_arxiv_with_journal_ref_is_article(self) -> None:
        reference = _reference(
            extra=(("primary_category", "math.NT"), ("journal_ref", "J. Number Theory 12 (2024)"))
        )
        entry = format_entry(reference)
        self.assertTrue(entry.startswith("@article{"))
        self.assertIn("journal = {J. Number Theory 12 (2024)},", entry)

    def test_crossref_journal_article_fields(self) -> None:
        reference = _reference(
            provider="crossref",
            ref_id="10.1000/j.jnt",
            venue="Journal of Number Theory",
            extra=(
                ("type", "journal-article"),
                ("volume", "12"),
                ("issue", "3"),
                ("pages", "1-20"),
            ),
        )
        entry = format_entry(reference)
        self.assertTrue(entry.startswith("@article{crossref_lovelace2024,"))
        self.assertIn("journal = {Journal of Number Theory},", entry)
        self.assertIn("volume = {12},", entry)
        self.assertIn("number = {3},", entry)
        self.assertIn("pages = {1-20},", entry)
        self.assertNotIn("archivePrefix", entry)

    def test_crossref_proceedings_uses_booktitle(self) -> None:
        reference = _reference(
            provider="crossref",
            venue="Proceedings of Examples",
            extra=(("type", "proceedings-article"),),
        )
        entry = format_entry(reference)
        self.assertTrue(entry.startswith("@inproceedings{"))
        self.assertIn("booktitle = {Proceedings of Examples},", entry)

    def test_pubmed_includes_pmid_note(self) -> None:
        reference = _reference(provider="pubmed", ref_id="12345678", venue="Nature")
        entry = format_entry(reference)
        self.assertEqual(entry_type(reference), "article")
        self.assertIn("note = {PMID: 12345678},", entry)

    def test_title_and_author_escaping(self) -> None:
        reference = _reference(
            title="Results & 50% Gains in K_theory #1",
            authors=("A & B Collective",),
        )
        entry = format_entry(reference)
        self.assertIn(r"Results \& 50\% Gains in K\_theory \#1", entry)
        self.assertIn(r"author = {A \& B Collective},", entry)

    def test_cite_key_fallback_without_year(self) -> None:
        reference = _reference(published="", authors=())
        self.assertEqual(generate_cite_key(reference), "arxiv_2401_00001v2")

    def test_bibliography_deduplicates_keys(self) -> None:
        first = _reference(title="Paper One")
        second = _reference(title="Paper Two", ref_id="2401.00002v1")
        bibliography = format_bibliography([first, second], "header note")
        self.assertTrue(bibliography.startswith("% header note"))
        self.assertIn("@misc{arxiv_lovelace2024,", bibliography)
        self.assertIn("@misc{arxiv_lovelace2024b,", bibliography)
