#!/usr/bin/env python3
"""Incremental indexer for the fox-corpus RAG source-of-truth.

Reads corpus/*.md, splits each into structure-aware chunks (heading-bounded,
code-fence-atomic, breadcrumb-prefixed), embeds changed chunks locally, and
writes a hybrid index (sqlite-vec vector search + FTS5 keyword search) to
index/corpus.db.

Incremental: only files whose content hash changed are re-chunked/re-embedded.
Deleted corpus files are pruned from the index.

Usage:  python ingest.py            # index changed files
        python ingest.py --rebuild  # wipe and rebuild everything
"""
from __future__ import annotations

import datetime
import hashlib
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec
from fastembed import TextEmbedding

# ── Config ───────────────────────────────────────────────────────────────────
# Paths, embedding model, and chunk sizing all come from config.toml via
# config.py, so the engine can point at any corpus without code edits.
from config import (  # noqa: E402
    ROOT, CORPUS_DIR, LOCAL_DIR, INBOX_DIR, DB_PATH, TIERS, INBOX_EXTS,
    EMBED_MODEL, EMBED_DIM, TARGET_CHARS, MAX_CHARS, MIN_CHARS, OVERLAP_CHARS,
)

BREADCRUMB_SEP = " › "
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


# ── Frontmatter ──────────────────────────────────────────────────────────────
def parse_frontmatter(text: str) -> tuple[dict, int]:
    """Return (metadata, body_line_offset). Offset = lines before the body."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, 0
    meta: dict = {}
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body_off = i + 1
            # skip a single blank line after the closing fence
            if body_off < len(lines) and not lines[body_off].strip():
                body_off += 1
            return meta, body_off
        m = re.match(r"^(\w+):\s*(.*)$", lines[i])
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key == "tags" and val.startswith("["):
                meta[key] = [t.strip() for t in val[1:-1].split(",") if t.strip()]
            else:
                meta[key] = val
    return meta, 0


# ── Inbox → local/ ───────────────────────────────────────────────────────────
DATA_URI_DEF = re.compile(r"^\s*\[[^\]]*\]:\s*<?\s*data:image/", re.IGNORECASE)
_FIRST_H1 = re.compile(r"^#\s+(.+)", re.MULTILINE)


def _slugify(stem: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return s or "untitled"


def _unique_slug(stem: str) -> str:
    """A slug not already used in local/ or corpus/."""
    base = _slugify(stem)
    slug, n = base, 2
    taken = {p.stem for p in LOCAL_DIR.rglob("*.md")} | {p.stem for p in CORPUS_DIR.rglob("*.md")}
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def process_inbox() -> int:
    """Turn raw files dropped in inbox/ into front-mattered docs in local/.

    Files that already carry YAML frontmatter are moved through as-is;
    others get a generated title/frontmatter. The original is removed from
    the inbox once its local/ copy exists. Returns the count processed.
    """
    if not INBOX_DIR.exists():
        return 0
    files = sorted(p for p in INBOX_DIR.iterdir()
                   if p.is_file() and p.suffix.lower() in INBOX_EXTS)
    LOCAL_DIR.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    count = 0
    for p in files:
        raw = "\n".join(l for l in p.read_text().split("\n") if not DATA_URI_DEF.match(l))
        raw = raw.strip("\n")
        slug = _unique_slug(p.stem)
        meta, _ = parse_frontmatter(raw)
        if meta:  # user supplied their own frontmatter — respect it
            content = raw + "\n"
        else:
            m = _FIRST_H1.search(raw)
            title = m.group(1).strip() if m else p.stem.replace("-", " ").replace("_", " ").title()
            front = (
                "---\n"
                f"title: {title}\n"
                f"source: inbox/{p.name}\n"
                "tags: []\n"
                "tier: local\n"
                f"added: {today}\n"
                "---\n\n"
            )
            content = front + raw + "\n"
        (LOCAL_DIR / f"{slug}.md").write_text(content)
        p.unlink()
        print(f"  inbox → local/{slug}.md  (from {p.name})")
        count += 1
    return count


# ── Chunking ─────────────────────────────────────────────────────────────────
@dataclass
class Segment:
    breadcrumb: list[str]           # ancestor titles + this heading
    level: int                      # heading level (0 = preamble before 1st heading)
    lines: list[tuple[int, str]]    # (body_line_index, text)
    is_atomic: bool = False         # contains a code fence — never split mid-block

    @property
    def text(self) -> str:
        return "\n".join(t for _, t in self.lines).strip()

    @property
    def start_idx(self) -> int:
        return self.lines[0][0]

    @property
    def end_idx(self) -> int:
        return self.lines[-1][0]


@dataclass
class Chunk:
    heading_path: str
    content: str
    start_line: int
    end_line: int


def segment_body(body_lines: list[str], root_title: str) -> list[Segment]:
    """Split body into heading-bounded segments, fence-aware, with breadcrumbs."""
    segments: list[Segment] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    cur: list[tuple[int, str]] = []
    cur_bc: list[str] = [root_title] if root_title else []
    cur_level = 0
    in_fence = False
    has_fence = False

    def flush():
        nonlocal cur, has_fence
        if any(t.strip() for _, t in cur):
            segments.append(Segment(list(cur_bc), cur_level, list(cur), has_fence))
        cur = []
        has_fence = False

    for idx, line in enumerate(body_lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            has_fence = True
            cur.append((idx, line))
            continue
        if not in_fence:
            m = HEADING_RE.match(line)
            if m:
                flush()
                level = len(m.group(1))
                title = m.group(2).strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                cur_bc = ([root_title] if root_title else []) + [t for _, t in stack]
                cur_level = level
                cur.append((idx, line))
                continue
        cur.append((idx, line))
    flush()
    return segments


def _split_oversized(seg: Segment, body_off: int) -> list[Chunk]:
    """Split a too-big segment on blank lines outside fences, with overlap."""
    bc = BREADCRUMB_SEP.join(seg.breadcrumb)
    prefix = f"[{bc}]\n\n"
    pieces: list[Chunk] = []
    buf: list[tuple[int, str]] = []
    in_fence = False

    def emit(carry: str = ""):
        if not any(t.strip() for _, t in buf):
            return ""
        start = body_off + buf[0][0] + 1
        end = body_off + buf[-1][0] + 1
        text = "\n".join(t for _, t in buf).strip()
        pieces.append(Chunk(bc, prefix + (carry + text if carry else text), start, end))
        # carry tail for overlap into the next piece
        return text[-OVERLAP_CHARS:] + "\n\n" if len(text) > OVERLAP_CHARS else text + "\n\n"

    carry = ""
    cur_chars = 0
    for idx, line in seg.lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
        buf.append((idx, line))
        cur_chars += len(line) + 1
        # only break at a blank line while not inside a fence
        if not in_fence and not line.strip() and cur_chars >= TARGET_CHARS:
            carry = emit(carry)
            buf = []
            cur_chars = 0
    if buf:
        emit(carry)
    return pieces


def chunk_file(path: Path) -> list[Chunk]:
    text = path.read_text()
    meta, body_off = parse_frontmatter(text)
    root_title = meta.get("title", path.stem)
    body_lines = text.split("\n")[body_off:]
    segments = segment_body(body_lines, root_title)

    chunks: list[Chunk] = []
    buf: list[Segment] = []
    buf_chars = 0

    def flush():
        nonlocal buf, buf_chars
        if not buf:
            return
        bc = BREADCRUMB_SEP.join(buf[0].breadcrumb)
        parts = []
        for i, s in enumerate(buf):
            # first segment already implies breadcrumb via prefix; keep raw text
            parts.append(s.text)
        content = f"[{bc}]\n\n" + "\n\n".join(parts)
        start = body_off + buf[0].start_idx + 1
        end = body_off + buf[-1].end_idx + 1
        chunks.append(Chunk(bc, content, start, end))
        buf = []
        buf_chars = 0

    for seg in segments:
        seg_len = len(seg.text)
        # An oversized segment gets its own split treatment.
        if seg_len > MAX_CHARS:
            flush()
            chunks.extend(_split_oversized(seg, body_off))
            continue
        # Force a fresh chunk before a major (H1/H2) heading — unless the
        # current buffer is still tiny (e.g. a lone title line), in which case
        # let it merge forward into this section instead of standing alone.
        if buf and seg.level in (1, 2) and buf_chars >= MIN_CHARS:
            flush()
        # Pack greedily up to TARGET.
        if buf and buf_chars + seg_len > TARGET_CHARS:
            flush()
        buf.append(seg)
        buf_chars += seg_len + 2
    flush()
    return chunks


# ── Index ────────────────────────────────────────────────────────────────────
def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def init_schema(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, hash TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY,
        doc_path TEXT, tier TEXT, title TEXT, tags TEXT,
        heading_path TEXT, content TEXT,
        start_line INTEGER, end_line INTEGER)""")
    db.execute(f"""CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks
        USING vec0(embedding float[{EMBED_DIM}])""")
    db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks
        USING fts5(content, heading_path, title, tokenize='porter unicode61')""")
    # Record embedding identity so a model change is detectable.
    cur = db.execute("SELECT value FROM meta WHERE key='embed_model'").fetchone()
    if cur and cur[0] != f"{EMBED_MODEL}:{EMBED_DIM}":
        raise SystemExit(
            f"Index was built with {cur[0]} but config is {EMBED_MODEL}:{EMBED_DIM}.\n"
            "Run:  python ingest.py --rebuild")
    db.execute("INSERT OR REPLACE INTO meta VALUES('embed_model', ?)",
               (f"{EMBED_MODEL}:{EMBED_DIM}",))
    db.commit()


def file_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def delete_doc(db: sqlite3.Connection, doc_path: str) -> None:
    ids = [r[0] for r in db.execute(
        "SELECT id FROM chunks WHERE doc_path=?", (doc_path,)).fetchall()]
    for cid in ids:
        db.execute("DELETE FROM vec_chunks WHERE rowid=?", (cid,))
        db.execute("DELETE FROM fts_chunks WHERE rowid=?", (cid,))
    db.execute("DELETE FROM chunks WHERE doc_path=?", (doc_path,))
    db.execute("DELETE FROM files WHERE path=?", (doc_path,))


def reindex(rebuild: bool = False) -> None:
    if rebuild and DB_PATH.exists():
        DB_PATH.unlink()

    moved = process_inbox()
    if moved:
        print(f"Processed {moved} inbox file(s) into local/.")

    db = connect()
    init_schema(db)

    # Scan every tier's folder; doc_path is prefixed by folder so tiers don't collide.
    disk: dict[str, tuple[str, Path]] = {}
    for tier, folder in TIERS:
        if not folder.exists():
            continue
        for p in sorted(folder.rglob("*.md")):  # recursive: supports the bucket scheme
            if p.name.lower() == "readme.md":   # folder READMEs are meta, not content
                continue
            rel = p.relative_to(folder).as_posix()
            disk[f"{folder.name}/{rel}"] = (tier, p)
    known = {r[0]: r[1] for r in db.execute("SELECT path, hash FROM files").fetchall()}

    # prune deleted files
    for gone in set(known) - set(disk):
        print(f"  - prune {gone}")
        delete_doc(db, gone)

    pending: list[tuple[str, str, dict, Chunk]] = []
    for doc_path, (tier, p) in disk.items():
        text = p.read_text()
        h = file_hash(text)
        if known.get(doc_path) == h:
            continue
        meta, _ = parse_frontmatter(text)
        delete_doc(db, doc_path)  # replace any prior version
        chs = chunk_file(p)
        for c in chs:
            pending.append((doc_path, tier, meta, c))
        db.execute("INSERT OR REPLACE INTO files VALUES(?, ?)", (doc_path, h))
        print(f"  ~ {doc_path} [{tier}]: {len(chs)} chunks")

    if not pending:
        print("Index up to date. Nothing to embed.")
        db.commit()
        return

    print(f"Embedding {len(pending)} chunks with {EMBED_MODEL} …")
    model = TextEmbedding(model_name=EMBED_MODEL)
    vectors = list(model.embed([c.content for *_, c in pending]))

    for (doc_path, tier, meta, c), vec in zip(pending, vectors):
        cur = db.execute(
            """INSERT INTO chunks
               (doc_path, tier, title, tags, heading_path, content, start_line, end_line)
               VALUES (?,?,?,?,?,?,?,?)""",
            (doc_path, tier, meta.get("title", ""), ",".join(meta.get("tags", [])),
             c.heading_path, c.content, c.start_line, c.end_line))
        cid = cur.lastrowid
        db.execute("INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
                   (cid, sqlite_vec.serialize_float32(vec.tolist())))
        db.execute(
            "INSERT INTO fts_chunks(rowid, content, heading_path, title) VALUES (?,?,?,?)",
            (cid, c.content, c.heading_path, meta.get("title", "")))
    db.commit()

    total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(f"Done. {len(pending)} chunks (re)indexed. Index holds {total} chunks total.")


if __name__ == "__main__":
    reindex(rebuild="--rebuild" in sys.argv)
