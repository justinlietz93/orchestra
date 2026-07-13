from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import Iterable

from .content_extractors import query_terms


WORD_PATTERN = re.compile(r"[\w]+", flags=re.UNICODE)
QUOTED_PHRASE_PATTERN = re.compile(r'"([^"]*)"')


@dataclass(frozen=True)
class QuotedPhrase:
    raw: str
    tokens: tuple[str, ...]

    @property
    def normalized(self) -> str:
        return " ".join(self.tokens)


@dataclass(frozen=True)
class ParsedSearchQuery:
    raw: str
    terms: tuple[str, ...]
    quoted_phrases: tuple[QuotedPhrase, ...]

    @property
    def match_mode(self) -> str:
        if self.quoted_phrases and self.terms:
            return "mixed"
        if self.quoted_phrases:
            return "quoted_phrase"
        if self.terms:
            return "broad_terms"
        return "empty"

    @property
    def fts_expression(self) -> str:
        phrase_clauses = [
            f'"{" ".join(phrase.tokens)}"'
            for phrase in self.quoted_phrases
        ]
        term_clauses = [f'"{term}"*' for term in self.terms]

        phrase_expression = " AND ".join(phrase_clauses)
        term_expression = " OR ".join(term_clauses)
        if phrase_expression and term_expression:
            return f"({phrase_expression}) AND ({term_expression})"
        return phrase_expression or term_expression


def parse_search_query(query: str) -> ParsedSearchQuery:
    phrases: list[QuotedPhrase] = []
    seen_phrases: set[tuple[str, ...]] = set()
    unquoted_parts: list[str] = []
    cursor = 0

    for match in QUOTED_PHRASE_PATTERN.finditer(query):
        unquoted_parts.append(query[cursor:match.start()])
        raw_phrase = match.group(1)
        tokens = normalized_word_tokens(raw_phrase)
        if tokens and tokens not in seen_phrases:
            seen_phrases.add(tokens)
            phrases.append(QuotedPhrase(raw_phrase, tokens))
        cursor = match.end()
    unquoted_parts.append(query[cursor:])

    terms = tuple(query_terms(" ".join(unquoted_parts)))
    return ParsedSearchQuery(query, terms, tuple(phrases))


def normalized_word_tokens(text: str) -> tuple[str, ...]:
    return tuple(
        match.group(0).casefold()
        for match in WORD_PATTERN.finditer(text)
    )


def fields_match_all_phrases(
    phrases: Iterable[QuotedPhrase],
    *fields: str | None,
) -> bool:
    searchable_fields = tuple(field or "" for field in fields)
    return all(
        any(
            _contains_token_sequence(field, phrase.tokens)
            for field in searchable_fields
        )
        for phrase in phrases
    )


def _contains_token_sequence(text: str, phrase: tuple[str, ...]) -> bool:
    if not phrase:
        return True
    window: deque[str] = deque(maxlen=len(phrase))
    for match in WORD_PATTERN.finditer(text):
        window.append(match.group(0).casefold())
        if len(window) == len(phrase) and tuple(window) == phrase:
            return True
    return False
