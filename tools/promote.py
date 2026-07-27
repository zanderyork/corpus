#!/usr/bin/env python3
"""Promote a doc from the private local/ tier to the canonical corpus/ tier.

    python tools/promote.py <name> [--force]

<name> is a local doc, with or without .md (e.g. 'my-notes' or 'my-notes.md').
The file is moved local/ → corpus/, its frontmatter tier flipped to canonical
(with a `promoted:` date), and the index rebuilt so retrieval reflects the move.

Nothing is pushed anywhere — corpus/ only becomes your remote source of truth
once you wire up and push to GitHub.
"""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = ROOT / "local"
CORPUS_DIR = ROOT / "corpus"


def set_canonical(text: str, date: str) -> str:
    """Flip `tier: local` → `tier: canonical` and stamp a promoted date."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text  # no frontmatter; leave content untouched
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return text
    block = lines[1:end]
    out, saw_tier, saw_promoted = [], False, False
    for ln in block:
        if re.match(r"^\s*tier:", ln):
            out.append("tier: canonical")
            saw_tier = True
        elif re.match(r"^\s*promoted:", ln):
            out.append(f"promoted: {date}")
            saw_promoted = True
        else:
            out.append(ln)
    if not saw_tier:
        out.append("tier: canonical")
    if not saw_promoted:
        out.append(f"promoted: {date}")
    return "\n".join(["---", *out, "---", *lines[end + 1:]])


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    if not args:
        print(__doc__)
        return 2

    name = args[0]
    if not name.endswith(".md"):
        name += ".md"
    src = LOCAL_DIR / Path(name).name
    dst = CORPUS_DIR / Path(name).name

    if not src.exists():
        avail = ", ".join(sorted(p.stem for p in LOCAL_DIR.glob("*.md"))) or "(none)"
        print(f"No local doc '{name}'. Local docs: {avail}", file=sys.stderr)
        return 1
    if dst.exists() and not force:
        print(f"corpus/{dst.name} already exists. Re-run with --force to overwrite.",
              file=sys.stderr)
        return 1

    today = datetime.date.today().isoformat()
    dst.write_text(set_canonical(src.read_text(), today))
    src.unlink()
    print(f"Promoted: local/{src.name} → corpus/{dst.name}")

    # Rebuild the index so the tier change is reflected immediately.
    sys.path.insert(0, str(ROOT))
    import ingest
    ingest.reindex()
    print("\nNow canonical. When your GitHub source of truth is set up: "
          "commit & push corpus/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
