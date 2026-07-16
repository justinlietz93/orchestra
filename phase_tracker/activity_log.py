"""Append-only activity ledger for observational analytics.

Records what the user does — searches, reindexes, external queries, exports,
batches — as one JSON line per event in `.project-handoff/activity.jsonl`.

Custody rules, same as every other ledger in Orchestra:
- Append-only; nothing here ever rewrites or deletes prior lines.
- Local-only; lives under `.project-handoff`, which the index crawler
  ignores, so activity never feeds back into search.
- Observational; recording never mutates workflow, archive, index, or
  workbench state, and a recording failure never breaks the action being
  recorded (errors are swallowed by design).

Pure module: standard library only, no Qt.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

ACTIVITY_FILE = Path(".project-handoff") / "activity.jsonl"


class ActivityLog:
    def __init__(self, root: Path) -> None:
        self.path = root / ACTIVITY_FILE
        self._lock = threading.Lock()

    def record(self, kind: str, **data: object) -> None:
        """Append one event. Never raises."""
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "data": data,
        }
        try:
            line = json.dumps(event, ensure_ascii=False, default=str)
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception:
            pass

    def read_events(self) -> list[dict]:
        """Read all events, skipping any malformed lines."""
        if not self.path.exists():
            return []
        events: list[dict] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict) and "kind" in event:
                        events.append(event)
        except OSError:
            return []
        return events
