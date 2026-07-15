"""Export external reference results as versioned JSON observations.

One exporter for every provider, one schema family:
`orchestra.<provider>-results-export`. Exports are derived, non-authoritative
observations written under `.project-handoff` where the index crawler never
looks, so external results can never feed back into local search.

Supersedes the arXiv-only exporter: the arXiv schema advances to version 2
under this family (provider-specific fields now live in each result's
`extra` object).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..references import ExternalQueryOutcome, PROVIDER_ENDPOINTS

SCHEMA_FAMILY = "orchestra.{provider}-results-export"
SCHEMA_VERSIONS = {"arxiv": 2}
DEFAULT_SCHEMA_VERSION = 1
EXPORT_DIRECTORY = Path(".project-handoff") / "search-exports"


@dataclass(frozen=True)
class ReferenceExportReceipt:
    export_id: str
    path: Path
    result_count: int


def schema_id(provider: str) -> str:
    return SCHEMA_FAMILY.format(provider=provider)


def schema_version(provider: str) -> int:
    return SCHEMA_VERSIONS.get(provider, DEFAULT_SCHEMA_VERSION)


def capture(outcome: ExternalQueryOutcome, search_duration_ms: float) -> dict[str, object]:
    export_id = uuid.uuid4().hex
    captured_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_id": schema_id(outcome.provider),
        "schema_version": schema_version(outcome.provider),
        "export_id": export_id,
        "captured_at": captured_at,
        "application": {"name": "orchestra", "version": __version__},
        "source": {
            "provider": outcome.provider,
            "endpoint": PROVIDER_ENDPOINTS.get(outcome.provider, ""),
            "authoritative": False,
        },
        "query": {
            "text": outcome.query,
            "search_duration_ms": round(float(search_duration_ms), 3),
            "total_available": outcome.total_available,
        },
        "results": [
            {
                "position": position,
                "ref_id": reference.ref_id,
                "title": reference.title,
                "authors": list(reference.authors),
                "summary": reference.summary,
                "venue": reference.venue,
                "published": reference.published,
                "url": reference.url,
                "pdf_url": reference.pdf_url,
                "doi": reference.doi,
                "extra": reference.extra_dict(),
            }
            for position, reference in enumerate(outcome.references, start=1)
        ],
        "totals": {"result_count": len(outcome.references)},
    }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "query"


def write(root: Path, captured: dict[str, object]) -> ReferenceExportReceipt:
    directory = root / EXPORT_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    captured_at = str(captured["captured_at"])
    timestamp = captured_at.replace(":", "").replace("-", "").split(".")[0]
    provider = str(captured["source"]["provider"])  # type: ignore[index]
    query_text = str(captured["query"]["text"])  # type: ignore[index]
    export_id = str(captured["export_id"])
    filename = f"{provider}-{timestamp}-{_slug(query_text)}-{export_id[:8]}.json"
    path = directory / filename
    path.write_text(json.dumps(captured, indent=2, ensure_ascii=False) + "\n")
    result_count = int(captured["totals"]["result_count"])  # type: ignore[index]
    return ReferenceExportReceipt(
        export_id=export_id, path=path, result_count=result_count
    )


def write_bibliography(root: Path, outcome: ExternalQueryOutcome, bibtex_text: str) -> Path:
    directory = root / EXPORT_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = (
        datetime.now(timezone.utc).isoformat().replace(":", "").replace("-", "").split(".")[0]
    )
    unique = uuid.uuid4().hex[:8]
    filename = f"bibtex-{outcome.provider}-{timestamp}-{_slug(outcome.query)}-{unique}.bib"
    path = directory / filename
    path.write_text(bibtex_text if bibtex_text.endswith("\n") else bibtex_text + "\n")
    return path
