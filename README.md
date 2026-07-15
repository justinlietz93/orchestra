![Orchestra Project Management](/assets/orchestra-banner-2.png)

> Current: v0.3.2  
> Latest release: v0.2.6

A local Linux desktop application for recording Operator, Guardian, and Auditor interactions without losing the project line, source artifacts, or handoff state.

## What it does

- Shows the currently active agent and the exact next handoff.
- Accepts files, ZIP packages, and whole directories by drag and drop.
- Stores the pasted agent response beside those artifacts.
- Lets only a fresh Auditor Pass or Fail create the next version, branch, or phase.
- Locks Auditor corrections after a Guardian failure to that same version.
- Records SHA-256 checksums and transition metadata in every version.
- Lets you browse and open everything under the selected project root.
- Builds a private, local search index over the project.
- Accepts natural-language-shaped searches and shows files from the same archived interaction as each direct match.
- Exports complete ranked search evidence to agent-friendly JSON with one click.
- Creates immutable, internal-only user Research Runs from explicitly selected project artifacts.
- Attaches hashed research summaries to p-b-v history without delivering them to an agent or changing workflow state.
- Switches cleanly between independent project roots.

![Orchestra Desktop View](/assets/orchestra-start-view.png)

## Install on Linux

Requirements:

- Python 3.11 or newer
- Internet access during the first installation
- Standard Linux desktop graphics libraries (`libegl1` and `libxkbcommon-x11-0` on Ubuntu)

From the extracted application directory:

```bash
./install.sh
```

The installer creates an isolated `.venv`, installs the GUI dependencies, verifies the Qt shared-library closure, creates a real test window, and then adds **Orchestra** to the desktop application menu. It does not alter the project repositories you later open.

You can also launch it directly:

```bash
./run.sh
./run.sh --root /absolute/path/to/project
```

### Upgrade from Project Handoff Tracker

Extract Orchestra beside the previous application directory and run `./install.sh` from the new `orchestra` directory. The installer replaces the old desktop launcher. Existing project roots retain their workflow state, event history, and search index because Orchestra reads the same backward-compatible `.project-handoff` metadata.

## Startup troubleshooting

The launcher writes both standard output and errors to:

```text
~/.local/state/orchestra/launch.log
```

If startup fails, the launcher displays that path through `zenity` or a desktop notification when either is available. Run the bundled diagnostic for the exact platform or shared-library failure:

```bash
./diagnose.sh
```

The common Ubuntu XCB repair is:

```bash
sudo apt install libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xkb1 libxcb-util1
```

## Record an interaction

1. Choose the project root. This is the directory that contains every phase.
2. Confirm the active phase and branch in **Active Line**.
3. Confirm the highlighted source agent and select the result of that agent's return.
4. Drop the returned package, files, or folders into the intake area.
5. Paste the complete response. The clipboard button is optional.
6. Choose the available archive action:

| Active return | Action | Destination |
| --- | --- | --- |
| Operator | Continue | Existing latest version |
| Guardian Pass | Continue | Existing latest version |
| Guardian Fail reviewing Operator | Continue | Existing version `operator-fails/` |
| Guardian Fail reviewing Auditor | Continue | Existing version `audit-fails/` |
| Fresh Auditor Pass or Fail | Continue | Next `vN` under the selected branch |
| Fresh Auditor Pass or Fail | New branch | Next `bN`, beginning at `v1` |
| Fresh Auditor Pass or Fail | New phase | Next `pN`, beginning at `b1/v1` |
| Auditor revision after Guardian Fail | Continue | Existing current version |

New Branch and New Phase are disabled for Operator returns, Guardian returns, and Auditor revisions. The full destination is shown before anything is written.

## Directory behavior

The canonical new layout is:

```text
project-root/
└── p5/
    └── p5-b3/
        └── p5-b3-v11/
            ├── auditor-package.zip
            ├── p5-b3-v11-auditor-response.md
            ├── AUDIT_RATIFICATION.md
            ├── operator-package.zip
            ├── p5-b3-v11-operator-response.md
            ├── audit-fails/
            │   └── p5-b3-v11-guardian-response.md
            ├── operator-fails/
            │   └── p5-b3-v11-guardian-response.md
            ├── p5-b3-v11-event-*-archive.json
            └── p5-b3-v11-archive.json
```

A fresh Auditor return that reports Pass or Fail opens the new version. If the Guardian rejects that Auditor return, Orchestra marks the next Auditor turn as a revision. Every corrected Auditor package and response remains in the same version until the Guardian passes it. Operator returns, Guardian ratifications, and Guardian failure notices also accumulate inside the active version.

Existing descriptive phase directories are also recognized. For example, this is treated as phase 5 and continued in place:

```text
project-root/
└── Phase-5_Prime_QBL/
    └── p5-b3/
        └── p5-b3-v10/
```

If **New phase** is selected while recording an Auditor Pass or Fail, the application creates `project-root/p6/p6-b1/p6-b1-v1` because a descriptive name for the new phase has not yet been supplied.

Two directories that both claim the same phase number are treated as an ambiguity. Archival stops until that conflict is resolved; the application never guesses which line is authoritative.

## Workflow transitions

| Return being recorded | Result | Next position |
| --- | --- | --- |
| Operator | Package produced | Guardian reviews Operator |
| Operator | Not produced | Operator repeats |
| Guardian reviewing Operator | Pass | Auditor receives ratification + Operator return |
| Guardian reviewing Operator | Fail | Operator revises and resubmits |
| Auditor | Pass or Fail | Guardian reviews Auditor |
| Guardian reviewing Auditor | Pass | Operator receives ratification + Auditor return |
| Guardian reviewing Auditor | Fail | Auditor revises and resubmits in the same version |
| Any active agent | Project complete | Project closes |

The Workflow menu can reopen a completed project or use **Set workflow position…** to align an existing project with Operator, Auditor, Auditor revising after Guardian failure, Guardian reviewing Operator, Guardian reviewing Auditor, or Project complete. Manual alignment is written to the project event history. It does not delete or rewrite archived evidence.

Projects last saved by Orchestra 0.2.0 are backward compatible. If the saved position is Auditor and the latest manifest is a Guardian failure of that Auditor, 0.2.1 recognizes it as a revision automatically.

In Orchestra 0.2.2, **Refresh project** and every completed archive rebuild the left file-tree model directly from disk. This avoids stale directory listings when filesystem watcher events are delayed or missed on mounted project drives. Expanded folders and the selected path are restored after the reload.

Orchestra 0.2.3 adds a reload icon beside **Project Files**. It refreshes only the file tree, without rescanning workflow coordinates or rebuilding the search index.

Orchestra 0.2.4 adds one-click JSON export for completed searches. Search exports do not change workflow position or project evidence.

Orchestra 0.2.5 adds exact quoted-phrase search. Unquoted queries keep the existing broad behavior. Double-quoted words must occur together and in order, without changing the index or workflow.

No reindex is required when upgrading from 0.2.4. Existing project search databases already contain the fields needed for quoted matching; reindex only when project files themselves have changed.

Orchestra 0.2.6 adds sequential batch search and export. Paste newline- or comma-separated queries into one editor, then run and export every query to the normal search-export directory. This upgrade also requires no reindex.

Orchestra 0.3.0 adds the user-only Research Workbench sidecar described below. It changes no search, export, batch, or workflow behavior and requires no reindex; workbench badges appear in results after the next reindex of a project that has attachments.

## Project search

The search index is stored at `.project-handoff/search.sqlite3` inside the selected project root. The internal directory name is retained for compatibility with projects created before the Orchestra name was adopted. Nothing is uploaded.

Each project, phase, branch, version, directory, and file is represented as a node. Parent-child containment is retained as graph edges. File names, paths, and extractable content are ranked with SQLite FTS5/BM25. Selecting a direct result expands the version node and lists the other files from that same archived interaction.

Use double quotes when word order matters:

```text
"Guardian rejected the audit"
```

Quoted phrases are case-insensitive and normalize punctuation and whitespace as word boundaries. The same normalized words must remain adjacent and in order. Unquoted terms retain broad OR-style prefix matching. A mixed query such as `"Guardian rejected" auditor` requires the exact quoted phrase and at least one broad match for `auditor`. Multiple quoted phrases are all required.

Indexed content includes:

- Markdown, plain text, logs, source code, Lean, JSON/JSONL, CSV/TSV, TOML, YAML, XML, and HTML
- Jupyter notebook source and text outputs
- PDF text through `pypdf`
- DOCX document text
- ZIP member paths and bounded text content inside ZIP packages

Very large text files are indexed from bounded head and tail regions. ZIP text extraction is also bounded. Binary contents are not decoded, but their file and member names remain searchable.

This release uses lexical ranking plus provenance-graph expansion. It does not pretend that lexical matching is an embedding model. The index schema leaves semantic vectors as an optional later layer if actual queries reveal stable synonym or concept-recall misses.

### Export search results

After any successful query, including one with zero matches, click **Export results**. Orchestra writes a collision-safe JSON file to:

```text
project-root/.project-handoff/search-exports/
```

No save dialog is shown, so a requested query list can be processed quickly: run a query, export it, and repeat. The export directory is visible beneath `.project-handoff` in Orchestra's file tree. Refresh that tree if the mounted filesystem does not notify the GUI immediately.

Each export contains:

- exact query text, match mode, normalized broad terms, quoted phrases, executed engine expression, timestamp, duration, limit, and returned count;
- ranked matches in display order with BM25 score semantics, paths, node kind, p-b-v coordinate, snippets, sizes, and modification times;
- the bounded **Same archived interaction** file set for every ranked match;
- explicit related-result limits and truncation flags;
- project and search-index snapshot metadata;
- Orchestra and export-schema versions, unique query-execution ID, and unique export ID;
- interpretation notes explaining that snippets are bounded and node IDs are index-local.

Exports are deliberately stored inside `.project-handoff`, which the search crawler ignores. Exporting results therefore cannot cause them to appear in later search results. See `docs/SEARCH_RESULTS_EXPORT.md` for the format contract.

### Batch queries

Click **Batch queries…** beside **Export results**, then paste or type the requested queries. Use one query per line. If the entire batch is on one line, commas separate its queries and commas inside double-quoted phrases are preserved. In multiline input, ordinary commas stay inside their query. Blank entries are ignored, order and duplicates are retained, and an unclosed double quote is reported before execution.

Click **Run and export** to process the list sequentially. A progress window shows the current position and can cancel before the next query. Each completed query, including a zero-match query, receives its own normal JSON file in `.project-handoff/search-exports/`.

Every file includes a shared `batch_execution_id`, the batch start time, its one-based position, and the original query count. Individual failures do not discard successful exports; Orchestra continues through the list and reports failed queries at the end. Batch search never changes phase, branch, version, active role, or workflow evidence.

## User Research Workbench

Orchestra 0.3.0 adds the first Research Workbench checkpoint as a separate, user-only sidecar. It is deliberately outside the Operator → Guardian → Auditor pipeline.

1. Search the project and select a graph result.
2. Click **Research selected graph node**.
3. Enter a campaign objective and explicitly select one or more project files.
4. Create the immutable internal-only run.
5. Review the hashed summary and attach it to a selected p-b-v record if desired.

An attachment is written beneath:

```text
<p-b-v>/user-research/<attachment-id>/
├── summary.md
├── provenance.json
└── artifact-links.json
```

The Workbench displays **USER RESEARCH**, **ATTACHED**, and **NOT PROVIDED** badges. Attachment records chronology only. It does not advance phase, branch, or version; change the active role; create an exposure event; imply agent awareness; or promote research into project canon.

Immutable run manifests and exact-byte content objects remain under `.project-handoff/workbench/`. Workbench metadata is stored in `.project-handoff/workbench.sqlite3`. Search indexes the attached p-b-v summary with its warning badges but does not index the private content-addressed object store.

Orchestra does not currently generate outbound agent packages. The Workbench nevertheless supplies and tests a default package exclusion policy: every Operator, Guardian, and Auditor package builder must omit `user-research/` unless a later, explicit role-specific exposure design is implemented. No such exposure action exists in this checkpoint.

See [Research Workbench checkpoint](docs/RESEARCH_WORKBENCH.md) for the exact boundary and storage model. The governing v2 ADR package is preserved unchanged at `docs/orchestra_research_workbench_adrs_v2.zip`.

## Provenance and write safety

Every completed version contains an archive manifest with:

- event ID and local timestamp
- phase, branch, and version coordinate
- source agent, result, next agent, and Guardian review subject
- next workflow state and handoff instruction
- SHA-256, size, and relative path for every copied file
- optional operator note

Every later return appended to that version receives a separate event manifest with the same evidence fields. Guardian failures and their manifests are placed under the corresponding fail directory.

Artifacts are first assembled in a staging directory. A new phase, branch, or version is moved into place as one filesystem operation. Current-version appends move collision-safe files from staging and commit their event manifest last. Tracker state is committed only after the controlling manifest exists. If the process stops between those operations, reopening the project validates the pending state against that exact manifest before recovering it.

Original files are copied, never moved. Same-named inputs receive `-2`, `-3`, and so on. Existing evidence is never overwritten.

## Test

The non-GUI engine uses only the Python standard library and can be tested without installing PySide:

```bash
./test.sh
```
