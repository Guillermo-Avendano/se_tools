"""Load knowledge files from workspace/knowledge/ into Qdrant.

Supported formats: .pdf, .txt, .md
Files are split into overlapping chunks and upserted into the same
Qdrant collection used for schema descriptions so the agent can
retrieve them as context.

For PDF files, the loader first generates a Markdown mirror under
workspace/knowledge/generated_md/ and indexes the generated Markdown
content so retrieval is cleaner than raw PDF extraction.

Uses a fingerprint file to skip re-embedding unchanged files on restart.
"""

import hashlib
import json
import os
from pathlib import Path

import structlog
from pypdf import PdfReader

from app.config import settings
from app.memory.qdrant_store import (
    get_qdrant_client,
    get_embeddings,
    ensure_collection,
    upsert_texts,
)

from app.skills.base import WORKSPACE_ROOT

logger = structlog.get_logger(__name__)

FILES_DIR = WORKSPACE_ROOT / "knowledge"

CHUNK_SIZE = 1000  # characters per chunk
CHUNK_OVERLAP = 200

# Fingerprint file stores {filename: md5_hash} to detect changes
_FINGERPRINT_PATH = FILES_DIR / ".doc_fingerprints.json"
_GENERATED_MD_DIR = FILES_DIR / "generated_md"
_LEGACY_GENERATED_MD_DIR = FILES_DIR / ".generated_md"
_MANUALS_DIR = FILES_DIR / "manuals"


# ── Readers ──────────────────────────────────────────────────

def _read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _clean_extracted_text(text: str) -> str:
    """Normalize extracted text to improve chunk quality."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    cleaned = "\n".join(lines)
    # Replace obvious null bytes and collapse repeated blank lines.
    cleaned = cleaned.replace("\x00", "")
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    return cleaned.strip()


def _markdown_path_for_pdf(pdf_path: Path) -> Path:
    """Return the generated Markdown path for a PDF file under FILES_DIR."""
    rel = pdf_path.relative_to(FILES_DIR)
    return (_GENERATED_MD_DIR / rel).with_suffix(".md")


def _convert_pdf_to_markdown(pdf_path: Path) -> Path:
    """Convert a PDF into a generated Markdown file and return its path."""
    md_path = _markdown_path_for_pdf(pdf_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(pdf_path))
    parts: list[str] = [f"# Converted from {pdf_path.name}"]
    for idx, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        text = _clean_extracted_text(raw)
        parts.append(f"\n## Page {idx}\n")
        parts.append(text if text else "(No extractable text)")

    md_text = "\n\n".join(parts).strip() + "\n"
    md_path.write_text(md_text, encoding="utf-8")
    logger.info("pdf_to_markdown.generated", source=pdf_path.name, markdown=str(md_path))
    return md_path


_READERS: dict[str, callable] = {
    ".pdf": _read_pdf,
    ".txt": _read_text,
    ".md": _read_text,
}


def _collection_has_points_of_type(client, collection: str, point_type: str) -> bool:
    """Return whether collection contains at least one point with payload type=point_type."""
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        count_result = client.count(
            collection_name=collection,
            count_filter=Filter(must=[
                FieldCondition(key="type", match=MatchValue(value=point_type))
            ]),
            exact=False,
        )
        return (count_result.count or 0) > 0
    except Exception as e:
        logger.warning("file_loader.count_error", type=point_type, error=str(e))
        # Fail open: do not force reindex if we cannot determine count.
        return True


# ── Chunker ──────────────────────────────────────────────────

def _split_text(text: str, chunk_size: int = CHUNK_SIZE,
                overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by character count."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# ── Fingerprinting ───────────────────────────────────────────

def _compute_file_hash(path: Path) -> str:
    """Return MD5 hex digest of a file's contents."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _pdf_markdown_missing(path: Path) -> bool:
    if path.suffix.lower() != ".pdf":
        return False
    return not _markdown_path_for_pdf(path).exists()


def _load_fingerprints() -> dict[str, str]:
    """Load the saved fingerprints or return empty dict."""
    if _FINGERPRINT_PATH.exists():
        try:
            return json.loads(_FINGERPRINT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_fingerprints(fp: dict[str, str]) -> None:
    """Persist fingerprints to disk."""
    _FINGERPRINT_PATH.write_text(json.dumps(fp, indent=2), encoding="utf-8")


def _collection_is_empty(client, collection: str) -> bool:
    """Return whether the Qdrant collection has zero points."""
    try:
        return (client.count(collection_name=collection, exact=False).count or 0) == 0
    except Exception as e:
        logger.warning("file_loader.collection_count_error", error=str(e))
        return False


def _regenerate_pdfs_to_generated_md() -> int:
    """Regenerate all PDF mirrors from knowledge/ into knowledge/generated_md/."""
    if not FILES_DIR.exists():
        return 0
    regenerated = 0
    for pdf_path in sorted(FILES_DIR.rglob("*.pdf")):
        rel_parts = pdf_path.relative_to(FILES_DIR).parts
        if rel_parts and rel_parts[0] in {"generated_md", ".generated_md"}:
            continue
        try:
            _convert_pdf_to_markdown(pdf_path)
            regenerated += 1
        except Exception as e:
            logger.warning("pdf_to_markdown.regenerate_error", file=str(pdf_path), error=str(e))
    if regenerated:
        logger.info("pdf_to_markdown.regenerated", files=regenerated)
    return regenerated


# ── Public API ───────────────────────────────────────────────

def load_files_for_memory(force_reindex: bool = False) -> int:
    """Read supported files in the root of FILES_DIR and upsert to Qdrant.

    Only indexes root-level files (not subdirectories like corrections/,
    procedures/, preferences/ which are handled by load_knowledge_for_memory).
    Uses fingerprinting to skip files that haven't changed since last run.
    Pass force_reindex=True to reindex all files regardless of fingerprints.
    Returns total number of newly indexed chunks.
    """
    if not FILES_DIR.exists():
        logger.info("file_loader.dir_missing", path=str(FILES_DIR))
        return 0

    # Root-level files in knowledge/
    root_files = [
        f for f in sorted(FILES_DIR.iterdir())
        if f.suffix.lower() in _READERS and f.is_file()
    ]
    # Pre-generated markdown files from PDF conversion (knowledge/generated_md/**)
    # These are indexed as documents so they are available for RAG retrieval.
    generated_md_files = sorted(_GENERATED_MD_DIR.rglob("*.md")) if _GENERATED_MD_DIR.exists() else []
    legacy_generated_md_files = sorted(_LEGACY_GENERATED_MD_DIR.rglob("*.md")) if _LEGACY_GENERATED_MD_DIR.exists() else []

    supported = root_files + [f for f in generated_md_files if f not in root_files]
    supported.extend([f for f in legacy_generated_md_files if f not in supported])
    if not supported:
        logger.info("file_loader.no_files")
        return 0

    client = get_qdrant_client()
    embeddings = get_embeddings()
    collection = settings.qdrant_collection
    ensure_collection(client, collection, embeddings)

    old_fp = _load_fingerprints()
    new_fp: dict[str, str] = {}

    # Determine which files changed
    changed_files: list[Path] = []
    for fpath in supported:
        # Use path relative to FILES_DIR as fingerprint key to avoid name collisions
        try:
            fp_key = str(fpath.relative_to(FILES_DIR))
        except ValueError:
            fp_key = fpath.name
        h = _compute_file_hash(fpath)
        new_fp[fp_key] = h
        if force_reindex or old_fp.get(fp_key) != h or _pdf_markdown_missing(fpath):
            changed_files.append(fpath)

    if not changed_files:
        has_documents = _collection_has_points_of_type(client, collection, "document")
        if not has_documents:
            logger.info("file_loader.reindex_required_empty_collection", files=len(supported))
            changed_files = list(supported)
        else:
            logger.info("file_loader.no_changes", files=len(supported), force_reindex=force_reindex)
            _save_fingerprints(new_fp)
            return 0

    logger.info("file_loader.changes_detected",
                changed=len(changed_files), total=len(supported))

    # Delete chunks for changed files only
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny
        changed_names = [f.name for f in changed_files]
        client.delete(
            collection_name=collection,
            points_selector=Filter(must=[
                FieldCondition(key="type", match=MatchValue(value="document")),
                FieldCondition(key="source", match=MatchAny(any=changed_names)),
            ]),
        )
        logger.info("file_loader.cleaned_changed", files=changed_names)
    except Exception as e:
        logger.warning("file_loader.cleanup_error", error=str(e))

    total = 0
    for fpath in changed_files:
        try:
            if fpath.suffix.lower() == ".pdf":
                md_path = _convert_pdf_to_markdown(fpath)
                raw = _read_text(md_path)
            else:
                reader_fn = _READERS[fpath.suffix.lower()]
                raw = reader_fn(fpath)
        except Exception as e:
            logger.error("file_loader.read_error", file=fpath.name, error=str(e))
            continue

        chunks = _split_text(raw)
        if not chunks:
            continue

        metas = [{"source": fpath.name, "type": "document"} for _ in chunks]
        count = upsert_texts(client, embeddings, collection, chunks, metas)
        logger.info("file_loader.indexed", file=fpath.name, chunks=count)
        total += count

    _save_fingerprints(new_fp)
    logger.info("file_loader.done", new_chunks=total, skipped=len(supported) - len(changed_files))
    return total


# ── Knowledge loader (agent learnings) ────────────────────────

KNOWLEDGE_DIR = WORKSPACE_ROOT / "knowledge"
_KNOWLEDGE_FP_PATH = KNOWLEDGE_DIR / ".fingerprints.json"

# Subdirectories explicitly indexed as knowledge sources.
_KNOWLEDGE_SOURCE_DIRS = {
    "manuals": "manual",
    "generated_md": "generated_md",
}

# Supported formats for categorized knowledge files.
_KNOWLEDGE_SUFFIXES = {".md", ".pdf"}


def _load_knowledge_fingerprints() -> dict[str, str]:
    if _KNOWLEDGE_FP_PATH.exists():
        try:
            return json.loads(_KNOWLEDGE_FP_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_knowledge_fingerprints(fp: dict[str, str]) -> None:
    _KNOWLEDGE_FP_PATH.parent.mkdir(parents=True, exist_ok=True)
    _KNOWLEDGE_FP_PATH.write_text(json.dumps(fp, indent=2), encoding="utf-8")


def load_knowledge_for_memory(force_reindex: bool = False) -> int:
    """Index knowledge Markdown files from manuals/ and generated_md/ into Qdrant.

    Uses fingerprinting to skip unchanged files. If Qdrant was wiped,
    all PDFs under knowledge/ are reprocessed into generated_md/ first,
    then markdown files are re-indexed.
    Pass force_reindex=True to ignore fingerprints and reindex all files.

    Returns total number of newly indexed chunks.
    """
    if not KNOWLEDGE_DIR.exists():
        logger.info("knowledge_loader.dir_missing", path=str(KNOWLEDGE_DIR))
        return 0

    client = get_qdrant_client()
    embeddings = get_embeddings()
    collection = settings.qdrant_collection
    ensure_collection(client, collection, embeddings)

    collection_empty = _collection_is_empty(client, collection)
    if collection_empty:
        _GENERATED_MD_DIR.mkdir(parents=True, exist_ok=True)
        _regenerate_pdfs_to_generated_md()

    # Gather supported markdown files only from manuals/ and generated_md/.
    all_files: list[tuple[Path, str]] = []  # (path, category)
    for subdir_name, category in _KNOWLEDGE_SOURCE_DIRS.items():
        subdir = KNOWLEDGE_DIR / subdir_name
        if not subdir.exists():
            continue
        for f in sorted(subdir.rglob("*")):
            if f.suffix.lower() == ".md" and f.is_file():
                all_files.append((f, category))

    if not all_files:
        logger.info("knowledge_loader.no_files")
        return 0

    old_fp = _load_knowledge_fingerprints()
    new_fp: dict[str, str] = {}

    changed: list[tuple[Path, str]] = []
    for fpath, category in all_files:
        key = str(fpath.relative_to(KNOWLEDGE_DIR))
        h = _compute_file_hash(fpath)
        new_fp[key] = h
        if force_reindex or collection_empty or old_fp.get(key) != h:
            changed.append((fpath, category))

    if not changed:
        has_knowledge = _collection_has_points_of_type(client, collection, "knowledge")
        if not has_knowledge:
            logger.info("knowledge_loader.reindex_required_empty_collection", files=len(all_files))
            changed = list(all_files)
        else:
            logger.info("knowledge_loader.no_changes", files=len(all_files), force_reindex=force_reindex)
            _save_knowledge_fingerprints(new_fp)
            return 0

    logger.info("knowledge_loader.changes_detected",
                changed=len(changed), total=len(all_files))

    # Delete changed knowledge chunks
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny
        changed_names = [f.name for f, _ in changed]
        client.delete(
            collection_name=collection,
            points_selector=Filter(must=[
                FieldCondition(key="type", match=MatchValue(value="knowledge")),
                FieldCondition(key="source", match=MatchAny(any=changed_names)),
            ]),
        )
    except Exception as e:
        logger.warning("knowledge_loader.cleanup_error", error=str(e))

    total = 0
    for fpath, category in changed:
        try:
            if fpath.suffix.lower() == ".pdf":
                md_path = _convert_pdf_to_markdown(fpath)
                raw = _read_text(md_path)
            else:
                reader_fn = _READERS.get(fpath.suffix.lower())
                if not reader_fn:
                    logger.warning("knowledge_loader.unsupported", file=fpath.name)
                    continue
                raw = reader_fn(fpath)
        except Exception as e:
            logger.error("knowledge_loader.read_error", file=fpath.name, error=str(e))
            continue

        chunks = _split_text(raw)
        if not chunks:
            continue

        metas = [{"source": fpath.name, "type": "knowledge", "category": category} for _ in chunks]
        count = upsert_texts(client, embeddings, collection, chunks, metas)
        logger.info("knowledge_loader.indexed", file=fpath.name, category=category, chunks=count)
        total += count

    _save_knowledge_fingerprints(new_fp)
    logger.info("knowledge_loader.done", new_chunks=total, skipped=len(all_files) - len(changed))
    return total
