from __future__ import annotations

import html
import json
import re
import zipfile
from pathlib import Path


TEXT_EXTENSIONS = {
    ".c", ".cc", ".cfg", ".conf", ".cpp", ".cs", ".css", ".csv", ".go",
    ".h", ".hpp", ".html", ".ini", ".java", ".js", ".json", ".jsonl",
    ".jsx", ".lean", ".log", ".md", ".mmd", ".py", ".r", ".rs", ".rst",
    ".sh", ".sql", ".tex", ".toml", ".ts", ".tsv", ".tsx", ".txt",
    ".xml", ".yaml", ".yml",
}
STOP_WORDS = {
    "a", "about", "all", "an", "and", "are", "as", "at", "be", "been",
    "but", "by", "can", "did", "do", "does", "file", "files", "find",
    "for", "from", "had", "has", "have", "how", "i", "in", "into", "is",
    "it", "me", "most", "of", "on", "or", "our", "project", "related",
    "show", "that", "the", "their", "there", "these", "this", "to", "was",
    "were", "what", "when", "where", "which", "who", "why", "with",
}
MAX_TEXT_BYTES = 10 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 2 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 8 * 1024 * 1024


def query_terms(query: str) -> list[str]:
    raw = re.findall(r"[\w]+", query.casefold(), flags=re.UNICODE)
    terms: list[str] = []
    seen: set[str] = set()
    for term in raw:
        if len(term) < 2 or term in STOP_WORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms[:24]


def extract_searchable_text(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in TEXT_EXTENSIONS:
        return _read_bounded_text(path)
    if suffix == ".ipynb":
        return _read_notebook(path)
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    if suffix == ".zip":
        return _read_zip(path)
    return ""


def _read_bounded_text(path: Path) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size <= MAX_TEXT_BYTES:
            data = handle.read()
        else:
            head_size = MAX_TEXT_BYTES * 4 // 5
            tail_size = MAX_TEXT_BYTES - head_size
            head = handle.read(head_size)
            handle.seek(max(0, size - tail_size))
            data = head + b"\n[... bounded index gap ...]\n" + handle.read(tail_size)
    if b"\x00" in data[:8192]:
        return ""
    return data.decode("utf-8", errors="replace")


def _read_notebook(path: Path) -> str:
    data = json.loads(_read_bounded_text(path))
    pieces: list[str] = []
    for cell in data.get("cells", []):
        source = cell.get("source", [])
        pieces.append("".join(source) if isinstance(source, list) else str(source))
        for output in cell.get("outputs", []):
            text = output.get("text")
            if text:
                pieces.append("".join(text) if isinstance(text, list) else str(text))
    return "\n".join(pieces)


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    reader = PdfReader(str(path))
    pieces: list[str] = []
    length = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        pieces.append(text)
        length += len(text.encode("utf-8", errors="ignore"))
        if length >= MAX_TEXT_BYTES:
            break
    return "\n".join(pieces)


def _read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        raw = archive.read("word/document.xml")
    text = re.sub(r"<[^>]+>", " ", raw.decode("utf-8", errors="replace"))
    return html.unescape(re.sub(r"\s+", " ", text))


def _read_zip(path: Path) -> str:
    pieces: list[str] = []
    consumed = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            pieces.append(info.filename)
            suffix = Path(info.filename).suffix.casefold()
            if info.is_dir() or suffix not in TEXT_EXTENSIONS | {".ipynb"}:
                continue
            if info.file_size > MAX_ZIP_MEMBER_BYTES or consumed >= MAX_ZIP_TOTAL_BYTES:
                continue
            raw = archive.read(info)
            consumed += len(raw)
            if b"\x00" not in raw[:8192]:
                pieces.append(raw.decode("utf-8", errors="replace"))
    return "\n".join(pieces)

