"""Derive analytics from Orchestra's ledgers.

Everything here is a read-model: metrics are recomputed on demand from the
activity ledger plus the evidence that already exists (workflow events,
workbench ledger, export directory). Nothing is cached, counted separately,
or written back — delete the derived report and nothing is lost; the ledgers
remain the single source of truth.

Pure module: standard library only, no Qt.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .activity_log import ActivityLog
from .references import PROVIDER_LABELS

REPORT_SCHEMA_ID = "orchestra.activity-report"
REPORT_SCHEMA_VERSION = 1
REPORT_DIRECTORY = Path(".project-handoff") / "reports"
EXPORT_DIRECTORY = Path(".project-handoff") / "search-exports"
EVENTS_FILE = Path(".project-handoff") / "events.jsonl"
WORKBENCH_DB = Path(".project-handoff") / "workbench.sqlite3"


def _event_day(event: dict) -> str:
    return str(event.get("ts", ""))[:10]


def _data(event: dict) -> dict:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def load_workflow_records(root: Path) -> list[dict]:
    """Read the workflow events journal, skipping malformed lines."""
    records: list[dict] = []
    events_path = root / EVENTS_FILE
    if not events_path.exists():
        return records
    try:
        with events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except OSError:
        return records
    return records


def iter_judgments(workflow_records: list[dict]) -> list[dict]:
    """Attribute every workflow verdict to (judging, judged).

    Guardian subjects are read from the event when present and inferred from
    the transition law for older history: Operator "Package produced" puts
    Operator under review; any Auditor event puts Auditor under review;
    manual alignments break the chain (subject becomes "unattributed").
    """
    judgments: list[dict] = []
    pending_subject: str | None = None
    for record in workflow_records:
        agent = str(record.get("source_agent", "")) or "unknown"
        result = str(record.get("result", "")) or "unknown"
        event_kind = str(record.get("event_type", ""))
        if event_kind == "manual_workflow_alignment":
            pending_subject = None
            continue
        judging = judged = None
        if agent == "Operator":
            judging, judged = "Operator", "Operator"
            pending_subject = "Operator" if result == "Package produced" else None
        elif agent == "Auditor":
            judging, judged = "Auditor", "Operator"
            pending_subject = "Auditor"
        elif agent == "Guardian":
            subject = record.get("guardian_subject") or pending_subject
            judging = "Guardian"
            judged = str(subject) if subject else "unattributed"
            pending_subject = None
        if judging is not None:
            judgments.append(
                {"record": record, "judging": judging, "judged": judged,
                 "result": result}
            )
    return judgments


def derive_metrics(root: Path) -> dict:
    """Compute the full metrics read-model for a project root."""
    events = ActivityLog(root).read_events()
    metrics: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "event_count": len(events),
        "first_event": events[0].get("ts", "") if events else "",
        "last_event": events[-1].get("ts", "") if events else "",
    }

    # Local searches
    searches = [event for event in events if event.get("kind") == "local_search"]
    modes = Counter(_data(event).get("mode", "unknown") for event in searches)
    zero_results = sum(1 for event in searches if _data(event).get("result_count") == 0)
    durations = [
        float(_data(event).get("duration_ms", 0.0))
        for event in searches
        if _data(event).get("duration_ms") is not None
    ]
    result_counts = [
        int(_data(event).get("result_count", 0)) for event in searches
    ]
    query_terms: Counter = Counter()
    for event in searches:
        for term in re.findall(r"[a-z0-9]+", str(_data(event).get("query", "")).lower()):
            if len(term) > 2:
                query_terms[term] += 1
    metrics["local_search"] = {
        "count": len(searches),
        "modes": dict(modes),
        "zero_result_count": zero_results,
        "zero_result_rate": round(zero_results / len(searches), 3) if searches else 0.0,
        "mean_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0.0,
        "mean_result_count": round(sum(result_counts) / len(result_counts), 2)
        if result_counts
        else 0.0,
        "top_terms": query_terms.most_common(10),
    }

    # Reindexes
    reindexes = [event for event in events if event.get("kind") == "reindex"]
    metrics["reindex"] = {
        "count": len(reindexes),
        "last_file_count": _data(reindexes[-1]).get("file_count") if reindexes else None,
    }

    # External searches per provider
    providers: dict[str, dict] = {}
    for event in events:
        if event.get("kind") != "external_search":
            continue
        data = _data(event)
        name = str(data.get("provider", "unknown"))
        stats = providers.setdefault(
            name,
            {"attempts": 0, "ok": 0, "failed": 0, "results_returned": 0},
        )
        stats["attempts"] += 1
        if data.get("ok"):
            stats["ok"] += 1
            stats["results_returned"] += int(data.get("result_count", 0))
        else:
            stats["failed"] += 1
    for stats in providers.values():
        stats["success_rate"] = (
            round(stats["ok"] / stats["attempts"], 3) if stats["attempts"] else 0.0
        )
    metrics["external_search"] = providers

    # Exports (from activity) and export files on disk (from the ledger dir)
    export_events = Counter(
        event.get("kind")
        for event in events
        if str(event.get("kind", "")).startswith("export_")
    )
    metrics["export_events"] = dict(export_events)
    files_by_prefix: Counter = Counter()
    export_dir = root / EXPORT_DIRECTORY
    if export_dir.exists():
        for path in export_dir.iterdir():
            if path.is_file():
                files_by_prefix[path.name.split("-", 1)[0]] += 1
    metrics["export_files_on_disk"] = dict(files_by_prefix)

    # Batches
    batches = [event for event in events if event.get("kind") == "batch"]
    metrics["batch"] = {
        "count": len(batches),
        "queries_executed": sum(int(_data(event).get("completed", 0)) for event in batches),
        "cancelled": sum(1 for event in batches if _data(event).get("cancelled")),
    }

    # Workflow events ledger (read-only) — the core of the project
    workflow_records = load_workflow_records(root)
    by_type = Counter(
        str(record.get("event_type", "event")) for record in workflow_records
    )
    agents: dict[str, dict] = {}
    per_phase: dict[str, Counter] = {}
    for record in workflow_records:
        agent = str(record.get("source_agent", "")) or "unknown"
        result = str(record.get("result", "")) or "unknown"
        stats = agents.setdefault(agent, {"events": 0, "results": Counter()})
        stats["events"] += 1
        stats["results"][result] += 1
        coordinate = record.get("coordinate")
        if isinstance(coordinate, dict) and coordinate.get("phase") is not None:
            phase_key = f"p{coordinate.get('phase')}"
            per_phase.setdefault(phase_key, Counter())[result] += 1
    workflow_agents: dict[str, dict] = {}
    for agent, stats in agents.items():
        results = stats["results"]
        passes = results.get("Pass", 0) + results.get("Package produced", 0)
        failures = results.get("Fail", 0) + results.get("Not produced", 0)
        judged = passes + failures
        workflow_agents[agent] = {
            "events": stats["events"],
            "results": dict(results),
            "passes": passes,
            "failures": failures,
            "pass_rate": round(passes / judged, 3) if judged else None,
        }
    # Judgment matrix: judging party x judged party -> pass/fail counts.
    # Guardian subjects are read from the event when present (recorded from
    # 0.3.5 on) and inferred from the transition law for older history:
    # Operator "Package produced" puts Operator under review; any Auditor
    # event puts Auditor under review; alignments break the chain.
    matrix: dict[tuple[str, str], Counter] = {}
    for judgment in iter_judgments(workflow_records):
        matrix.setdefault(
            (judgment["judging"], judgment["judged"]), Counter()
        )[judgment["result"]] += 1

    def _cell(judging: str, judged: str) -> dict:
        counts = matrix.get((judging, judged), Counter())
        passes = counts.get("Pass", 0) + counts.get("Package produced", 0)
        failures = counts.get("Fail", 0) + counts.get("Not produced", 0)
        judged_total = passes + failures
        return {
            "passes": passes,
            "failures": failures,
            "judged_total": judged_total,
            "pass_rate": round(passes / judged_total, 3) if judged_total else None,
        }

    judgment_matrix = {
        f"{judging}->{judged}": _cell(judging, judged)
        for (judging, judged) in sorted(matrix)
    }

    def _combine(cells: list[dict]) -> dict:
        passes = sum(cell["passes"] for cell in cells)
        failures = sum(cell["failures"] for cell in cells)
        total = passes + failures
        return {
            "passes": passes,
            "failures": failures,
            "judged_total": total,
            "pass_rate": round(passes / total, 3) if total else None,
        }

    granted = {
        "Operator": {
            "Operator": _cell("Operator", "Operator"),
            "overall": _cell("Operator", "Operator"),
        },
        "Guardian": {
            "Operator": _cell("Guardian", "Operator"),
            "Auditor": _cell("Guardian", "Auditor"),
            "overall": _combine(
                [_cell("Guardian", "Operator"), _cell("Guardian", "Auditor")]
            ),
        },
        "Auditor": {
            "Operator": _cell("Auditor", "Operator"),
            "overall": _cell("Auditor", "Operator"),
        },
    }
    received = {
        "Operator": {
            "Operator": _cell("Operator", "Operator"),
            "Guardian": _cell("Guardian", "Operator"),
            "Auditor": _cell("Auditor", "Operator"),
            "overall": _combine(
                [
                    _cell("Operator", "Operator"),
                    _cell("Guardian", "Operator"),
                    _cell("Auditor", "Operator"),
                ]
            ),
        },
        "Auditor": {
            "Guardian": _cell("Guardian", "Auditor"),
            "overall": _cell("Guardian", "Auditor"),
        },
    }
    unattributed = _cell("Guardian", "unattributed")

    metrics["workflow"] = {
        "event_count": len(workflow_records),
        "judgment_matrix": judgment_matrix,
        "granted": granted,
        "received": received,
        "unattributed_guardian_reviews": unattributed,
        "by_type": dict(by_type),
        "agents": workflow_agents,
        "per_phase": {phase: dict(counts) for phase, counts in sorted(per_phase.items())},
        "first_event": str(workflow_records[0].get("recorded_at", ""))
        if workflow_records
        else "",
        "last_event": str(workflow_records[-1].get("recorded_at", ""))
        if workflow_records
        else "",
    }

    # Workbench ledger (read-only row counts)
    workbench: dict[str, int] = {}
    db_path = root / WORKBENCH_DB
    if db_path.exists():
        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                tables = [
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                    if not row[0].startswith("sqlite_")
                ]
                for table in tables:
                    count = connection.execute(
                        f'SELECT COUNT(*) FROM "{table}"'
                    ).fetchone()[0]
                    workbench[table] = int(count)
            finally:
                connection.close()
        except sqlite3.Error:
            pass
    metrics["workbench_tables"] = workbench

    # Daily activity across BOTH ledgers, most recent 14 days
    per_day = Counter(_event_day(event) for event in events if _event_day(event))
    for record in workflow_records:
        day = str(record.get("recorded_at", ""))[:10]
        if day:
            per_day[day] += 1
    today = datetime.now(timezone.utc).date()
    days = []
    for offset in range(13, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        days.append((day, per_day.get(day, 0)))
    metrics["daily_activity"] = days

    # Recent feed merged from both ledgers, newest first
    merged: list[dict] = [
        {"ts": event.get("ts", ""), "kind": event.get("kind", ""), "data": _data(event)}
        for event in events
    ]
    for record in workflow_records:
        merged.append(
            {
                "ts": str(record.get("recorded_at", "")),
                "kind": str(record.get("event_type", "workflow")),
                "data": {
                    "agent": record.get("source_agent", ""),
                    "result": record.get("result", ""),
                    "coordinate": record.get("coordinate", ""),
                },
            }
        )
    merged.sort(key=lambda event: str(event.get("ts", "")))
    metrics["recent"] = merged[-25:][::-1]
    metrics["total_recorded"] = len(events) + len(workflow_records)
    metrics["is_empty"] = metrics["total_recorded"] == 0

    return metrics


def render_markdown(metrics: dict) -> str:
    lines = [
        "# Orchestra Activity Report",
        "",
        f"Generated {metrics['generated_at']} · Orchestra {__version__} · "
        f"{metrics['event_count']} recorded events "
        f"({metrics['first_event'][:10]} to {metrics['last_event'][:10]})"
        if metrics["event_count"]
        else f"Generated {metrics['generated_at']} · Orchestra {__version__} · no recorded events yet",
        "",
        "## Local search",
        "",
    ]
    local = metrics["local_search"]
    modes = ", ".join(f"{name}: {count}" for name, count in local["modes"].items()) or "none"
    lines.append(
        f"{local['count']} searches ({modes}). Mean duration "
        f"{local['mean_duration_ms']} ms, mean results {local['mean_result_count']}, "
        f"zero-result rate {local['zero_result_rate']:.1%}."
    )
    if local["top_terms"]:
        terms = ", ".join(f"{term} ({count})" for term, count in local["top_terms"])
        lines.append(f"Top terms: {terms}.")
    lines.extend(["", "## External providers", ""])
    if metrics["external_search"]:
        for provider, stats in sorted(metrics["external_search"].items()):
            label = PROVIDER_LABELS.get(provider, provider)
            lines.append(
                f"{label}: {stats['attempts']} attempts, {stats['ok']} ok, "
                f"{stats['failed']} failed ({stats['success_rate']:.1%} success), "
                f"{stats['results_returned']} results returned."
            )
    else:
        lines.append("No external searches recorded.")
    lines.extend(["", "## Exports and batches", ""])
    exports = ", ".join(
        f"{kind.removeprefix('export_')}: {count}"
        for kind, count in sorted(metrics["export_events"].items())
    ) or "none recorded"
    disk = ", ".join(
        f"{prefix}: {count}"
        for prefix, count in sorted(metrics["export_files_on_disk"].items())
    ) or "none"
    batch = metrics["batch"]
    lines.append(f"Export actions: {exports}. Files on disk: {disk}.")
    lines.append(
        f"Batches: {batch['count']} run, {batch['queries_executed']} queries executed, "
        f"{batch['cancelled']} cancelled."
    )
    lines.extend(["", "## Workflow steps", ""])
    workflow = metrics["workflow"]
    if workflow["event_count"]:
        lines.append(
            f"{workflow['event_count']} workflow events "
            f"({workflow['first_event'][:10]} to {workflow['last_event'][:10]})."
        )
        for agent, stats in sorted(workflow["agents"].items()):
            rate = (
                f"{stats['pass_rate']:.1%} pass rate"
                if stats["pass_rate"] is not None
                else "no judged results"
            )
            results = ", ".join(
                f"{result}: {count}" for result, count in sorted(stats["results"].items())
            )
            lines.append(
                f"{agent}: {stats['events']} events — {results} ({rate})."
            )
        def _fmt(cell: dict) -> str:
            if cell["judged_total"] == 0:
                return "no judged results"
            return (
                f"{cell['pass_rate']:.1%} "
                f"({cell['passes']}/{cell['judged_total']})"
            )

        lines.append("")
        lines.append("Judging (verdicts granted):")
        granted = workflow["granted"]
        lines.append(
            f"- Operator, package produced: {_fmt(granted['Operator']['Operator'])}"
        )
        lines.append(
            f"- Guardian -> Operator: {_fmt(granted['Guardian']['Operator'])}; "
            f"Guardian -> Auditor: {_fmt(granted['Guardian']['Auditor'])}; "
            f"overall: {_fmt(granted['Guardian']['overall'])}"
        )
        lines.append(
            f"- Auditor -> Operator: {_fmt(granted['Auditor']['Operator'])}"
        )
        lines.append("")
        lines.append("Judged (verdicts received):")
        received = workflow["received"]
        lines.append(
            f"- Operator: by self {_fmt(received['Operator']['Operator'])}; "
            f"by Guardian {_fmt(received['Operator']['Guardian'])}; "
            f"by Auditor {_fmt(received['Operator']['Auditor'])}; "
            f"overall {_fmt(received['Operator']['overall'])}"
        )
        lines.append(
            f"- Auditor: by Guardian {_fmt(received['Auditor']['Guardian'])}"
        )
        if workflow["unattributed_guardian_reviews"]["judged_total"]:
            lines.append(
                "- Unattributed Guardian reviews (subject unknown): "
                f"{_fmt(workflow['unattributed_guardian_reviews'])}"
            )
        if workflow["per_phase"]:
            lines.append("")
            lines.append("Per phase:")
            for phase, counts in workflow["per_phase"].items():
                summary = ", ".join(
                    f"{result}: {count}" for result, count in sorted(counts.items())
                )
                lines.append(f"- {phase}: {summary}")
    else:
        lines.append("No workflow events recorded.")
    lines.extend(["", "## Ledgers", ""])
    workbench = ", ".join(
        f"{table}: {count}" for table, count in sorted(metrics["workbench_tables"].items())
    ) or "no workbench ledger"
    lines.append(f"Workbench ledger — {workbench}.")
    lines.extend(["", "## Daily activity (last 14 days)", ""])
    for day, count in metrics["daily_activity"]:
        bar = "#" * min(count, 60)
        lines.append(f"{day}  {count:>4}  {bar}")
    lines.append("")
    return "\n".join(lines)


def write_report(root: Path, metrics: dict) -> tuple[Path, Path]:
    """Write the JSON observation and its markdown rendering; return both paths."""
    directory = root / REPORT_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    report_id = uuid.uuid4().hex
    timestamp = (
        metrics["generated_at"].replace(":", "").replace("-", "").split(".")[0]
    )
    payload = {
        "schema_id": REPORT_SCHEMA_ID,
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_id": report_id,
        "application": {"name": "orchestra", "version": __version__},
        "derived_from": [
            "activity.jsonl", "events.jsonl", "workbench.sqlite3", "search-exports/",
        ],
        "metrics": metrics,
    }
    json_path = directory / f"activity-report-{timestamp}-{report_id[:8]}.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    md_path = json_path.with_suffix(".md")
    md_path.write_text(render_markdown(metrics))
    return json_path, md_path
