from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

from ..search_engine import ProjectSearchIndex
from .exporter import SearchExportReceipt, SearchResultsExporter


ProgressCallback = Callable[[int, int, str], None]
CancellationCheck = Callable[[], bool]


@dataclass(frozen=True)
class BatchQueryFailure:
    position: int
    query: str
    message: str


@dataclass(frozen=True)
class BatchExportReport:
    batch_execution_id: str
    started_at: str
    query_count: int
    completed_query_count: int
    receipts: tuple[SearchExportReceipt, ...]
    failures: tuple[BatchQueryFailure, ...]
    cancelled: bool


def split_batch_queries(text: str) -> list[str]:
    queries: list[str] = []
    current: list[str] = []
    inside_quotes = False
    comma_separated = "\n" not in text and "\r" not in text

    def finish_query() -> None:
        query = "".join(current).strip()
        current.clear()
        if query:
            queries.append(query)

    for character in text:
        if character == '"':
            inside_quotes = not inside_quotes
            current.append(character)
        elif (
            character in {"\n", "\r"}
            or (character == "," and comma_separated)
        ) and not inside_quotes:
            finish_query()
        else:
            current.append(character)

    if inside_quotes:
        raise ValueError("A quoted phrase is missing its closing double quote.")
    finish_query()
    return queries


def export_batch_queries(
    index: ProjectSearchIndex,
    queries: Sequence[str],
    *,
    result_limit: int = 40,
    related_limit: int = 30,
    progress: ProgressCallback | None = None,
    cancelled: CancellationCheck | None = None,
) -> BatchExportReport:
    normalized_queries = tuple(query.strip() for query in queries if query.strip())
    batch_execution_id = _identifier("bq")
    started_at = _utc_now()
    receipts: list[SearchExportReceipt] = []
    failures: list[BatchQueryFailure] = []
    was_cancelled = False
    exporter = SearchResultsExporter(index)

    for position, query in enumerate(normalized_queries, start=1):
        if cancelled and cancelled():
            was_cancelled = True
            break
        try:
            search_started = time.perf_counter()
            results = index.search(query, limit=result_limit)
            duration_ms = (time.perf_counter() - search_started) * 1000
            captured = exporter.capture(
                query,
                results,
                result_limit=result_limit,
                related_limit=related_limit,
                search_duration_ms=duration_ms,
                batch={
                    "batch_execution_id": batch_execution_id,
                    "started_at": started_at,
                    "position": position,
                    "query_count": len(normalized_queries),
                },
            )
            receipts.append(exporter.write(captured))
        except Exception as error:
            failures.append(BatchQueryFailure(position, query, str(error)))
        if progress:
            progress(position, len(normalized_queries), query)

    completed = len(receipts) + len(failures)
    return BatchExportReport(
        batch_execution_id=batch_execution_id,
        started_at=started_at,
        query_count=len(normalized_queries),
        completed_query_count=completed,
        receipts=tuple(receipts),
        failures=tuple(failures),
        cancelled=was_cancelled,
    )


def _identifier(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:12]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
