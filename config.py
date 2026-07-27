"""Central configuration for the corpus engine.

Values load from `config.toml` (committed defaults), optionally overlaid by
`config.local.toml` (gitignored, per-machine). Every other module imports its
paths / model / chunk settings from here — so pointing the engine at a
different corpus (e.g. your app monorepo's `corpus/`) is a config change, not
a code change. That decoupling is what lets one engine serve any team's docs.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent

_DEFAULTS: dict[str, dict] = {
    "paths": {
        "corpus": "corpus",          # canonical tier (your source of truth)
        "local": "local",            # private tier (indexed, never pushed)
        "inbox": "inbox",            # drop zone (processed into local/)
        "index": "index/corpus.db",  # generated hybrid index
    },
    "embedding": {
        "model": "BAAI/bge-base-en-v1.5",
        "dim": 768,
    },
    "chunking": {
        "target_chars": 2800,
        "max_chars": 4200,
        "min_chars": 400,
        "overlap_chars": 200,
    },
}


def _load() -> dict:
    cfg = {section: dict(vals) for section, vals in _DEFAULTS.items()}
    for name in ("config.toml", "config.local.toml"):
        p = ROOT / name
        if p.exists():
            data = tomllib.loads(p.read_text())
            for section, vals in data.items():
                cfg.setdefault(section, {}).update(vals)
    return cfg


_cfg = _load()


def _path(value: str) -> Path:
    q = Path(value).expanduser()
    return q if q.is_absolute() else (ROOT / q)


# Paths
CORPUS_DIR = _path(_cfg["paths"]["corpus"])
LOCAL_DIR = _path(_cfg["paths"]["local"])
INBOX_DIR = _path(_cfg["paths"]["inbox"])
DB_PATH = _path(_cfg["paths"]["index"])

# Embedding
EMBED_MODEL = str(_cfg["embedding"]["model"])
EMBED_DIM = int(_cfg["embedding"]["dim"])

# Chunking
TARGET_CHARS = int(_cfg["chunking"]["target_chars"])
MAX_CHARS = int(_cfg["chunking"]["max_chars"])
MIN_CHARS = int(_cfg["chunking"]["min_chars"])
OVERLAP_CHARS = int(_cfg["chunking"]["overlap_chars"])

# Derived
TIERS: list[tuple[str, Path]] = [("canonical", CORPUS_DIR), ("local", LOCAL_DIR)]
INBOX_EXTS = {".md", ".markdown", ".txt"}
