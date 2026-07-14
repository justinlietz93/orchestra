# Research Workbench — First Vertical Slice

## Architectural assessment

The v2 ADR package draws the right boundary for Orchestra. Research is useful project context, but silently treating it as agent input would weaken the provenance guarantees the tracker exists to protect. The smallest credible proof is therefore local and deliberately asymmetric: the Workbench may read project evidence and attach chronology, but it cannot write pipeline state or assert delivery.

This checkpoint follows that boundary without adopting Cogito's controlling architecture.

## Implemented checkpoint

- Launch a separate Workbench window from a selected search graph node.
- Create one user-owned campaign and one completed internal-only Research Run.
- Accept only explicitly selected regular files beneath the project root.
- Reject symlinks and Orchestra control files as research inputs.
- Snapshot exact bytes into a SHA-256 content-addressed object store.
- Generate a bounded, deterministic Markdown summary from locally extracted text.
- Hash the summary and record its source hashes and object paths.
- Write immutable run, provenance, and artifact-link records.
- Attach the exact summary to a selected existing p-b-v folder.
- Display `USER RESEARCH`, `ATTACHED`, and `NOT PROVIDED` badges.
- Keep all three role delivery states at `not_provided`.
- Keep the exposure ledger empty.
- Exclude `user-research/` through the default handoff candidate policy for Operator, Guardian, and Auditor.

External connectors, planner DAGs, critique councils, outbound agent delivery, explicit exposure manifests, claim promotion, and publication bundles are intentionally absent.

## Component map

| Concern | Reused Orchestra component | Workbench addition |
| --- | --- | --- |
| Desktop navigation | `SearchPanel`, graph-result selection | `WorkbenchLaunchBar`, separate dialog |
| Project graph | `ProjectSearchIndex` | Attachment badges only |
| Text extraction | `content_extractors.py` | Bounded deterministic summary renderer |
| Hashing | `archive_files.sha256_file` | Content-addressed object store |
| p-b-v discovery | `discovery.scan_project` | Read-only target selector |
| Workflow | No Workbench dependency | Byte-for-byte non-mutation tests |
| Persistence | Existing `.project-handoff/` control root | Separate `workbench.sqlite3` ledger |
| Background jobs | Existing Qt worker/thread pattern | Run snapshot and summary worker |
| Package generation | No outbound builder exists | Mandatory default exclusion policy |

## Storage layout

```text
project-root/
├── .project-handoff/
│   ├── state.json                         # untouched by Workbench
│   ├── events.jsonl                       # untouched by Workbench
│   ├── search.sqlite3                     # disposable derived index
│   ├── workbench.sqlite3                  # Workbench metadata ledger
│   └── workbench/
│       ├── objects/sha256/ab/<sha256>     # immutable exact content
│       └── runs/<run-id>/
│           ├── run.json
│           ├── provenance.json
│           └── artifact-links.json
└── <phase>/<branch>/<version>/
    └── user-research/<attachment-id>/
        ├── summary.md
        ├── provenance.json
        └── artifact-links.json
```

The run manifest hash is SHA-256 over canonical UTF-8 JSON with sorted keys, compact separators, and `manifest_hash` set to `null`. The resulting digest is then stored in `manifest_hash`. This avoids a self-referential hash while making the verification rule deterministic.

Run and attachment directory names are collision-resistant IDs. Files are created exclusively, staged, hash-checked, and moved into place. SQLite foreign keys and immutable update/delete triggers protect the metadata records. If the final database commit fails, the newly staged run or attachment directory is removed; content-addressed objects may remain as harmless deduplicated orphans for a later garbage-collection checkpoint.

## State semantics

The following states remain independent:

```text
created ≠ attached ≠ provided ≠ acknowledged ≠ relied on
        ≠ audited ≠ adopted ≠ published
```

The run provenance records `created=true` and every later state as false. The attachment provenance records its p-b-v chronology and all three roles as `not_provided`. Neither attaching nor indexing inserts an exposure event.

## Cogito capability review

No Cogito code is needed for this slice. Potential future donors, evaluated one capability at a time, are provider connectors, query planning interfaces, deduplication, citation normalization, and rendering helpers.

Excluded from Orchestra are Cogito's controlling orchestration, project layout, mutable output model, provider-driven synthesis assumptions, direct delivery behavior, and any component capable of workflow advancement. A static architecture test prevents Workbench imports or calls across that mutation boundary.

## Migration

No destructive migration is required. On first Workbench use, Orchestra creates `workbench.sqlite3` with schema version 1 and the Workbench object/run directories. Existing tracker state, event history, archived evidence, and search indexes remain compatible. Search must be reindexed once to discover newly attached summaries.

## Verification

Run:

```bash
./test.sh
```

The suite proves workflow state remains byte-for-byte unchanged, p-b-v does not advance, attachments create no exposure, all role states remain `not_provided`, indexing creates no exposure, all three default role package candidate sets exclude `user-research/`, and no Workbench module can invoke pipeline mutation or Cogito control code.

## Exact next checkpoint

Add a read-only Campaign/Run browser with manifest re-verification and orphan diagnostics. Do not add external connectors or agent exposure yet. That checkpoint should validate the local immutable record model under real use before expanding research capability or introducing the explicit role-specific exposure ledger described by ADR-0013.
