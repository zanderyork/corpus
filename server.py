#!/usr/bin/env python3
"""fox-corpus MCP server (stdio).

Exposes the technical-spec corpus to agents as three tools:
  • search_specs(query, k)  — hybrid vector + keyword retrieval, cited
  • get_doc(path)           — full topic file, on demand
  • list_docs()             — the corpus table of contents

Humans write corpus/*.md and run ingest.py; agents only read through here.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import sqlite_vec
from fastembed import TextEmbedding
from mcp.server.fastmcp import FastMCP

from config import ROOT, CORPUS_DIR, DB_PATH, EMBED_MODEL  # noqa: E402

RRF_K = 60  # reciprocal-rank-fusion constant

mcp = FastMCP("corpus")

_model: TextEmbedding | None = None
_db: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _db
    if _db is None:
        if not DB_PATH.exists():
            raise RuntimeError("Index not built. Run: python ingest.py")
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True,
                               check_same_thread=False)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _db = conn
    return _db


def model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=EMBED_MODEL)
    return _model


def _fts_query(query: str) -> str | None:
    """Turn free text into a safe FTS5 OR-query (avoids syntax errors)."""
    terms = re.findall(r"[A-Za-z0-9_]+", query)
    return " OR ".join(terms) if terms else None


def _hybrid_ids(query: str, k: int) -> list[int]:
    """Return chunk ids ranked by reciprocal rank fusion of vector + FTS."""
    conn = db()
    pool = max(k * 4, 20)

    qvec = list(model().query_embed(query))[0]
    vec_rows = conn.execute(
        "SELECT rowid FROM vec_chunks WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
        (sqlite_vec.serialize_float32(qvec.tolist()), pool)).fetchall()

    fts_rows = []
    fq = _fts_query(query)
    if fq:
        try:
            fts_rows = conn.execute(
                "SELECT rowid FROM fts_chunks WHERE fts_chunks MATCH ? "
                "ORDER BY bm25(fts_chunks) LIMIT ?", (fq, pool)).fetchall()
        except sqlite3.OperationalError:
            fts_rows = []

    scores: dict[int, float] = {}
    for rank, (rid,) in enumerate(vec_rows):
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (RRF_K + rank)
    for rank, (rid,) in enumerate(fts_rows):
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (RRF_K + rank)

    ranked = sorted(scores, key=lambda r: scores[r], reverse=True)
    return ranked[:k]


@mcp.tool()
def search_specs(query: str, k: int = 5) -> str:
    """Search the Newsroom App technical corpus for the passages most relevant
    to a question. Uses hybrid semantic + keyword retrieval. Returns the top
    matching sections, each with its source file, line range, and heading path
    so answers can be cited and verified. Use this first for any factual
    question about the project's specs, procedures, config, or commands.

    Args:
        query: A natural-language question or keywords.
        k: How many passages to return (default 5, max 20).
    """
    k = max(1, min(int(k), 20))
    ids = _hybrid_ids(query, k)
    if not ids:
        return f"No matches for: {query!r}"
    conn = db()
    placeholders = ",".join("?" * len(ids))
    rows = {r[0]: r for r in conn.execute(
        f"SELECT id, doc_path, tier, heading_path, content, start_line, end_line "
        f"FROM chunks WHERE id IN ({placeholders})", ids).fetchall()}

    out = [f"Top {len(ids)} result(s) for: {query!r}\n"]
    for i, cid in enumerate(ids, 1):
        _, doc_path, tier, heading_path, content, start, end = rows[cid]
        badge = "" if tier == "canonical" else f" [{tier}]"
        out.append(f"### {i}. {heading_path}{badge}")
        out.append(f"source: {doc_path}:{start}-{end}")
        out.append("")
        out.append(content.strip())
        out.append("\n" + "-" * 60)
    return "\n".join(out)


@mcp.tool()
def get_doc(path: str) -> str:
    """Return the full text of a corpus topic file. Use after search_specs when
    a passage isn't enough and you need the whole document for context.

    Args:
        path: A corpus file, e.g. 'rollback-procedure' or 'corpus/rollback-procedure.md'.
    """
    rel = path.strip()
    if rel.startswith("corpus/"):
        rel = rel[len("corpus/"):]
    cand = Path(rel)
    if cand.suffix != ".md":
        cand = cand.with_suffix(".md")
    target = (CORPUS_DIR / cand).resolve()
    if CORPUS_DIR.resolve() in target.parents and target.exists():
        return target.read_text()
    # Fallback: unique match by filename stem anywhere in the corpus.
    matches = [p for p in CORPUS_DIR.rglob("*.md") if p.stem == Path(rel).stem]
    if len(matches) == 1:
        return matches[0].read_text()
    avail = ", ".join(sorted(str(p.relative_to(CORPUS_DIR)) for p in CORPUS_DIR.rglob("*.md"))) or "(corpus is empty)"
    return f"No such doc: {path!r}. Available: {avail}"


@mcp.tool()
def list_docs() -> str:
    """List every document in the corpus with its title, tags, and section
    count — the table of contents. Use to discover what topics exist before
    searching or fetching a specific doc."""
    conn = db()
    rows = conn.execute(
        "SELECT doc_path, tier, title, tags, COUNT(*) FROM chunks "
        "GROUP BY doc_path ORDER BY tier DESC, doc_path").fetchall()
    if not rows:
        return "Corpus is empty. Run: python ingest.py"
    out = [f"{len(rows)} documents in the corpus:\n"]
    last_tier = None
    for doc_path, tier, title, tags, n in rows:
        if tier != last_tier:
            label = "canonical (source of truth)" if tier == "canonical" else "local (private, not pushed)"
            out.append(f"── {label} ──")
            last_tier = tier
        out.append(f"• {doc_path}  ({n} sections)")
        out.append(f"    {title}")
        if tags:
            out.append(f"    tags: {tags}")
    return "\n".join(out)


if __name__ == "__main__":
    mcp.run()
