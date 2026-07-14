from __future__ import annotations

import copy
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from .. import __version__
from ..search_engine import ProjectSearchIndex, RelatedFile, SearchResult
from ..search_query import parse_search_query
from .metadata import index_snapshot, path_metadata


SCHEMA_ID = "orchestra.search-results-export"
SCHEMA_VERSION = 2
EXPORT_DIRECTORY = Path(".project-handoff") / "search-exports"


@dataclass(frozen=True)
class SearchExportReceipt:
    export_id: str
    path: Path
    ranked_match_count: int


class SearchResultsExporter:
    def __init__(self, index: ProjectSearchIndex):
        self.index = index
        self.root = index.root

    def capture(
        self,
        query: str,
        results: Sequence[SearchResult],
        *,
        result_limit: int = 40,
        related_limit: int = 30,
        search_duration_ms: float | None = None,
        batch: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        execution_id = self._identifier("sq")
        captured_at = self._utc_now()
        parsed_query = parse_search_query(query)
        ranked_matches: list[dict[str, object]] = []
        unique_related_paths: set[str] = set()
        total_related_memberships = 0

        for position, result in enumerate(results, start=1):
            candidates = self.index.related_files(
                result.node_id,
                related_limit + 1,
            )
            related = candidates[:related_limit]
            unique_related_paths.update(item.path for item in related)
            total_related_memberships += len(related)
            coordinate = self._coordinate(
                result.phase,
                result.branch,
                result.version,
            )
            ranked_matches.append({
                "position": position,
                "score": {
                    "algorithm": "sqlite_fts5_bm25",
                    "value": result.rank,
                    "lower_is_better": True,
                },
                "node": self._result_node(result),
                "snippet": self._clean_snippet(result.snippet),
                "snippet_with_match_markers": result.snippet,
                "same_archived_interaction": {
                    "relation": "same_phase_branch_version",
                    "coordinate": coordinate,
                    "limit": related_limit,
                    "returned_count": len(related),
                    "truncated": len(candidates) > related_limit,
                    "files": [
                        self._related_node(item, coordinate)
                        for item in related
                    ],
                },
            })

        duration = (
            round(search_duration_ms, 3)
            if search_duration_ms is not None
            else None
        )
        return {
            "schema_id": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "query_execution_id": execution_id,
            "captured_at": captured_at,
            "exported_at": None,
            "application": {"name": "Orchestra", "version": __version__},
            "batch": copy.deepcopy(dict(batch)) if batch else None,
            "project": {
                "name": self.root.name,
                "root": str(self.root),
            },
            "query": {
                "raw": query,
                "match_mode": parsed_query.match_mode,
                "normalized_terms": list(parsed_query.terms),
                "quoted_phrases": [
                    {
                        "raw": phrase.raw,
                        "normalized": phrase.normalized,
                        "tokens": list(phrase.tokens),
                    }
                    for phrase in parsed_query.quoted_phrases
                ],
                "engine_expression": parsed_query.fts_expression,
                "matching_semantics": {
                    "quoted_phrases": (
                        "all_required_as_case_insensitive_adjacent_token_sequences"
                        if parsed_query.quoted_phrases
                        else "not_applicable"
                    ),
                    "unquoted_terms": (
                        "at_least_one_broad_prefix_term_required"
                        if parsed_query.terms
                        else "not_applicable"
                    ),
                    "punctuation_and_whitespace": "normalized_as_token_boundaries",
                },
                "executed_at": captured_at,
                "result_limit": result_limit,
                "returned_count": len(results),
                "result_limit_reached": len(results) >= result_limit,
                "search_duration_ms": duration,
            },
            "index_snapshot": index_snapshot(self.index),
            "ranking": {
                "algorithm": "SQLite FTS5 BM25",
                "ordering": "ascending_score",
                "score_note": "Lower BM25 values rank before higher values.",
                "quoted_phrase_post_filter": bool(parsed_query.quoted_phrases),
            },
            "ranked_matches": ranked_matches,
            "summary": {
                "ranked_match_count": len(ranked_matches),
                "related_file_memberships": total_related_memberships,
                "unique_related_file_count": len(unique_related_paths),
            },
            "interpretation_notes": [
                "Snippets are bounded index excerpts, not complete file contents.",
                "Same archived interaction means a shared phase, branch, and version.",
                "Node IDs are local to this disposable search-index snapshot.",
                "Quoted phrases require the same normalized words together and in order.",
            ],
        }

    def write(self, captured: dict[str, object]) -> SearchExportReceipt:
        payload = copy.deepcopy(captured)
        exported_at = self._utc_now()
        export_id = self._identifier("se")
        payload["export_id"] = export_id
        payload["exported_at"] = exported_at
        query = payload.get("query", {})
        raw_query = str(query.get("raw", "")) if isinstance(query, dict) else ""
        filename = self._filename(exported_at, raw_query, export_id)
        directory = self.root / EXPORT_DIRECTORY
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / filename
        temporary = directory / f".{filename}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        matches = payload.get("ranked_matches", [])
        return SearchExportReceipt(
            export_id,
            destination,
            len(matches) if isinstance(matches, list) else 0,
        )

    def _result_node(self, result: SearchResult) -> dict[str, object]:
        node = path_metadata(self.root, result.path, result.name, result.kind)
        node.update({
            "node_id": result.node_id,
            "coordinate": self._coordinate(
                result.phase,
                result.branch,
                result.version,
            ),
        })
        return node

    def _related_node(
        self,
        related: RelatedFile,
        coordinate: dict[str, int | None],
    ) -> dict[str, object]:
        node = path_metadata(self.root, related.path, related.name, "file")
        node.update({"node_id": related.node_id, "coordinate": coordinate})
        return node

    @staticmethod
    def _coordinate(
        phase: int | None,
        branch: int | None,
        version: int | None,
    ) -> dict[str, int | None]:
        return {"phase": phase, "branch": branch, "version": version}

    @staticmethod
    def _clean_snippet(snippet: str) -> str:
        return " ".join(re.sub(r"</?mark>", "", snippet).split())

    @staticmethod
    def _filename(exported_at: str, query: str, export_id: str) -> str:
        stamp = re.sub(r"[-:.Z+]", "", exported_at)[:18]
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:48]
        return f"search-{stamp}-{slug or 'empty-query'}-{export_id[-8:]}.json"

    @staticmethod
    def _identifier(prefix: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"{prefix}_{stamp}_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
