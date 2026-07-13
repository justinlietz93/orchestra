# Architecture

## Authority split

The application keeps five concerns separate:

1. `discovery.py` reads the existing phase/branch/version structure and computes unused destinations.
2. `workflow.py` owns the Operator/Guardian/Auditor state machine.
3. `archive_policy.py` grants coordinate creation only to an Auditor Pass or Fail and routes all other returns into the current version.
4. `archive.py` performs staged copies, hashes artifacts, writes authoritative manifests, and commits tracker state.
5. `search_engine.py` derives a disposable local retrieval index from project files. The search database is never authoritative project evidence.

The GUI calls these modules but does not reproduce their rules.

## Archive transaction

```mermaid
flowchart TD
    A[Validate source and result] --> B{Auditor Pass or Fail?}
    B -->|Yes| C[Create next coordinate]
    B -->|No| D[Select current-version folder]
    C --> E[Stage files and manifest]
    D --> E
    E --> F[Commit archive evidence]
    F --> G[Commit prepared state]
    G --> H[Append convenience event row]
```

The coordinate-creation manifest and every append-event manifest contain the full next state. The root-level state file is the fast resume pointer. A pending pointer is accepted during recovery only when its event ID matches the exact manifest named by that pending state.

## Retrieval graph

```mermaid
flowchart TD
    P[Project] --> H[Phase]
    H --> B[Branch]
    B --> V[Version]
    V --> D[Directory]
    V --> F[File]
    D --> F2[Nested file]
```

Nodes store their coordinate and filesystem path. FTS results identify direct matching nodes. The version coordinate supplies the bounded relation expansion used by **Same archived interaction**.

## Local metadata

```text
project-root/.project-handoff/
├── state.json
├── state.pending.json    # exists only during a commit or recoverable interruption
├── events.jsonl
└── search.sqlite3
```

`events.jsonl` is a convenience timeline. Per-version manifests remain the authoritative evidence if the event journal ever requires reconstruction.
