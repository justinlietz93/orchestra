# Search Results Export

Orchestra 0.2.5 captures a successful project query as portable JSON. The format is designed for returning many search runs to an agent without manually copying each match and related-file list.

## Fast workflow

1. Enter and run the requested query.
2. Click **Export results**.
3. Repeat for every requested query.
4. Retrieve the files from `.project-handoff/search-exports/` under the project root.
5. Select or archive those JSON files and return them to the requesting agent.

The button is enabled for zero-match queries because absence is still a useful search result.

## Format identity

```json
{
  "schema_id": "orchestra.search-results-export",
  "schema_version": 2,
  "query_execution_id": "sq_...",
  "captured_at": "2026-07-13T12:34:56.789Z",
  "export_id": "se_...",
  "exported_at": "2026-07-13T12:35:01.123Z"
}
```

`query_execution_id` identifies one completed query capture. Clicking the export button twice creates two distinct files and export IDs while preserving the same query-execution ID.

Schema version 2 adds explicit quoted-query semantics. The `query` record contains `match_mode`, normalized unquoted terms, raw and normalized quoted phrases, the FTS engine expression, and machine-readable matching rules. Values for `match_mode` are `broad_terms`, `quoted_phrase`, `mixed`, and `empty`.

## Query matching

- Unquoted terms retain broad OR-style prefix matching and FTS stemming.
- Words inside ASCII double quotes must occur together and in order.
- Quoted matching is case-insensitive and treats punctuation and whitespace as token boundaries.
- Every quoted phrase is required.
- A mixed query requires every phrase and at least one unquoted broad term.

For example, `"Guardian rejected the audit" bridge` requires that exact normalized phrase plus a broad match for `bridge`. The engine uses FTS5 to rank candidates and checks the original indexed fields afterward so stemming cannot loosen a quoted phrase.

## Ranked matches

`ranked_matches` preserves the exact display order. Every entry contains:

- one-based `position`;
- the SQLite FTS5 BM25 value and the explicit rule that lower values rank first;
- index-local node ID;
- project-relative path, name, node kind, and p-b-v coordinate;
- existence, size, modification time, and symlink state at capture time;
- a clean snippet and a copy retaining `<mark>` match markers;
- a nested `same_archived_interaction` record.

The related record contains files sharing the direct match's phase, branch, and version. It records its limit, returned count, and whether additional files were truncated. Related memberships are intentionally nested under each ranked match even when the same path occurs under multiple matches.

## Index snapshot

The export records the search database path, byte size, modification time, nanosecond mtime, indexed project root, node count, and file-node count. This identifies which disposable index snapshot produced the ranking without pretending the index is authoritative project evidence.

## Safety properties

- Exports do not alter phase, branch, version, active agent, or workflow state.
- Exports do not modify archived interaction manifests.
- Files are written through a temporary file and atomically moved into place.
- Unique IDs prevent repeated clicks from overwriting earlier exports.
- `.project-handoff` is excluded from the search crawler, preventing self-indexing loops.
- Snippets remain bounded excerpts; an export is not a replacement for the underlying project artifacts.
