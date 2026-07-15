"""Convert external reference records to BibTeX.

Ported from Cogito's BibTexConverter and hardened: citation keys are
deduplicated, months use standard BibTeX macros, LaTeX special characters
are escaped, and entry types follow the record's provider and venue. Pure
module: no Qt, no network, standard library only.
"""

from __future__ import annotations

import re

from .references import ExternalReference

_MONTH_MACROS = {
    "01": "jan", "02": "feb", "03": "mar", "04": "apr",
    "05": "may", "06": "jun", "07": "jul", "08": "aug",
    "09": "sep", "10": "oct", "11": "nov", "12": "dec",
}

_ESCAPES = [
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("$", r"\$"),
]


def escape_value(text: str) -> str:
    for raw, escaped in _ESCAPES:
        text = text.replace(raw, escaped)
    return text


def _year_of(reference: ExternalReference) -> str:
    match = re.search(r"(\d{4})", reference.published)
    return match.group(1) if match else ""


def _month_of(reference: ExternalReference) -> str:
    match = re.search(r"\d{4}-(\d{2})", reference.published)
    return _MONTH_MACROS.get(match.group(1), "") if match else ""


def generate_cite_key(reference: ExternalReference) -> str:
    author_part = "unknown"
    if reference.authors:
        surname = reference.authors[0].split()[-1].lower()
        author_part = re.sub(r"[^a-z0-9]", "", surname) or "unknown"
    year_part = _year_of(reference)
    if year_part:
        return f"{reference.provider}_{author_part}{year_part}"
    ref_id = re.sub(r"[^A-Za-z0-9]", "_", reference.ref_id) or "ref"
    return f"{reference.provider}_{ref_id}"


def entry_type(reference: ExternalReference) -> str:
    extra = reference.extra_dict()
    if reference.provider == "arxiv":
        return "article" if extra.get("journal_ref") else "misc"
    if reference.provider == "crossref":
        kind = extra.get("type", "")
        return {
            "journal-article": "article",
            "proceedings-article": "inproceedings",
            "book-chapter": "incollection",
            "book": "book",
            "monograph": "book",
        }.get(kind, "misc")
    if reference.provider == "pubmed":
        return "article"
    return "article" if reference.venue else "misc"


def format_entry(reference: ExternalReference, cite_key: str | None = None) -> str:
    extra = reference.extra_dict()
    kind = entry_type(reference)
    key = cite_key or generate_cite_key(reference)
    lines = [f"@{kind}{{{key},"]
    if reference.authors:
        author_string = " and ".join(
            escape_value(author) for author in reference.authors
        )
        lines.append(f"  author = {{{author_string}}},")
    lines.append(f"  title = {{{{{escape_value(reference.title)}}}}},")
    year = _year_of(reference)
    if year:
        lines.append(f"  year = {{{year}}},")
    month = _month_of(reference)
    if month:
        lines.append(f"  month = {month},")

    if reference.provider == "arxiv":
        journal_ref = extra.get("journal_ref", "")
        if journal_ref:
            lines.append(f"  journal = {{{escape_value(journal_ref)}}},")
        lines.append(f"  eprint = {{{reference.ref_id}}},")
        lines.append("  archivePrefix = {arXiv},")
        primary = extra.get("primary_category", "")
        if primary:
            lines.append(f"  primaryClass = {{{primary}}},")
    else:
        venue_field = {
            "article": "journal",
            "inproceedings": "booktitle",
            "incollection": "booktitle",
        }.get(kind)
        if venue_field and reference.venue:
            lines.append(f"  {venue_field} = {{{escape_value(reference.venue)}}},")
        for source_key, bib_key in (
            ("volume", "volume"),
            ("issue", "number"),
            ("pages", "pages"),
            ("publisher", "publisher"),
        ):
            value = extra.get(source_key, "")
            if value:
                lines.append(f"  {bib_key} = {{{escape_value(value)}}},")
        if reference.provider == "pubmed" and reference.ref_id:
            lines.append(f"  note = {{PMID: {reference.ref_id}}},")

    if reference.doi:
        lines.append(f"  doi = {{{reference.doi}}},")
    if reference.url:
        lines.append(f"  url = {{{reference.url}}},")
    lines.append("}")
    return "\n".join(lines)


def format_bibliography(
    references: list[ExternalReference] | tuple[ExternalReference, ...],
    header_comment: str = "",
) -> str:
    contents: list[str] = []
    if header_comment:
        contents.append(f"% {header_comment}")
        contents.append("")
    used_keys: dict[str, int] = {}
    for reference in references:
        base = generate_cite_key(reference)
        count = used_keys.get(base, 0)
        used_keys[base] = count + 1
        key = base if count == 0 else f"{base}{chr(ord('a') + count)}"
        contents.append(format_entry(reference, key))
        contents.append("")
    return "\n".join(contents)
