![Orchestra Project Management](/assets/orchestra-banner-2.png)

A local Linux desktop application for recording Operator, Guardian, and Auditor interactions without losing the project line, source artifacts, or handoff state.

## What it does

- Shows the currently active agent and the exact next handoff.
- Accepts files, ZIP packages, and whole directories by drag and drop.
- Stores the pasted agent response beside those artifacts.
- Lets only an Auditor Pass or Fail create the next version, branch, or phase.
- Records SHA-256 checksums and transition metadata in every version.
- Lets you browse and open everything under the selected project root.
- Builds a private, local search index over the project.
- Accepts natural-language-shaped searches and shows files from the same archived interaction as each direct match.
- Switches cleanly between independent project roots.

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
| Auditor Pass or Fail | Continue | Next `vN` under the selected branch |
| Auditor Pass or Fail | New branch | Next `bN`, beginning at `v1` |
| Auditor Pass or Fail | New phase | Next `pN`, beginning at `b1/v1` |

New Branch and New Phase are disabled for Operator and Guardian returns. The full destination is shown before anything is written.

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

The Auditor return that reports Pass or Fail opens the new version. Operator returns, Guardian ratifications, and Guardian failure notices accumulate inside that version until the next Auditor Pass or Fail opens the following version.

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
| Guardian reviewing Auditor | Fail | Auditor revises and resubmits |
| Any active agent | Project complete | Project closes |

The Workflow menu can reopen a completed project or use **Set workflow position…** to align an existing project with Operator, Auditor, Guardian reviewing Operator, Guardian reviewing Auditor, or Project complete. Manual alignment is written to the project event history. It does not delete or rewrite archived evidence.

## Project search

The search index is stored at `.project-handoff/search.sqlite3` inside the selected project root. The internal directory name is retained for compatibility with projects created before the Orchestra name was adopted. Nothing is uploaded.

Each project, phase, branch, version, directory, and file is represented as a node. Parent-child containment is retained as graph edges. File names, paths, and extractable content are ranked with SQLite FTS5/BM25. Selecting a direct result expands the version node and lists the other files from that same archived interaction.

Indexed content includes:

- Markdown, plain text, logs, source code, Lean, JSON/JSONL, CSV/TSV, TOML, YAML, XML, and HTML
- Jupyter notebook source and text outputs
- PDF text through `pypdf`
- DOCX document text
- ZIP member paths and bounded text content inside ZIP packages

Very large text files are indexed from bounded head and tail regions. ZIP text extraction is also bounded. Binary contents are not decoded, but their file and member names remain searchable.

This release uses lexical ranking plus provenance-graph expansion. It does not pretend that lexical matching is an embedding model. The index schema leaves semantic vectors as an optional later layer if actual queries reveal stable synonym or concept-recall misses.

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
