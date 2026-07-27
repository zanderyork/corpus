# Corpus — local hybrid-RAG source of truth

A **self-contained engine** that turns a folder of Markdown docs into a
**cited, always-current knowledge source** your AI agents can query — running
entirely on your machine, with no external services and no data leaving your
laptop.

You point it at a corpus of docs; it chunks, embeds, and indexes them locally,
then serves them to agents (Claude Code and any other MCP client) through three
tools: **search, fetch, and list**. Agents get the few relevant, cited
passages instead of a giant document.

```
docs (Markdown)  ──ingest──▶  local hybrid index  ──serve──▶  agents
 source of truth   chunk+embed   sqlite-vec + FTS5    MCP stdio   search_specs / get_doc / list_docs
```

> This repo is the **engine** (the reusable infrastructure). Your *content*
> lives wherever you point it (see [Pointing at your own corpus](#pointing-the-engine-at-your-own-corpus)).
> The engine and the content are deliberately separate, so one engine can serve
> any team's docs.

---

## Table of contents

- [What you get](#what-you-get)
- [Requirements & prerequisites](#requirements--prerequisites)
- [Quickstart](#quickstart)
- [How it works](#how-it-works)
- [Adding content — the inbox workflow](#adding-content--the-inbox-workflow)
- [Two operating modes: solo vs team](#two-operating-modes-solo-vs-team)
- [Pointing the engine at your own corpus](#pointing-the-engine-at-your-own-corpus)
- [Using it from agents (MCP)](#using-it-from-agents-mcp)
- [Organization scheme](#organization-scheme)
- [Command reference](#command-reference)
- [Scaling & model upgrades](#scaling--model-upgrades)
- [Repo layout](#repo-layout)

---

## What you get

- **Local & private.** Embeddings run in-process (no server, no GPU, no cloud).
  Nothing is sent anywhere.
- **Hybrid retrieval.** Semantic vector search (`sqlite-vec`) *and* keyword
  search (FTS5), fused with reciprocal rank fusion — so exact terms (command
  names, metric IDs) and fuzzy questions both land.
- **Cited answers.** Every result carries its source `file:line-range` and
  heading path, so agents can point you at the exact spot.
- **Two tiers of truth.** A private `local/` tier for personal notes and a
  shared `corpus/` tier you promote into — see [modes](#two-operating-modes-solo-vs-team).
- **Incremental.** Only changed files are re-embedded; deleted files are pruned.
- **Engine-agnostic content.** Your docs are plain Markdown + YAML frontmatter.
  Swap the whole engine later and the corpus is untouched.

## Requirements & prerequisites

| Requirement | Notes |
|-------------|-------|
| **Python 3.11+** | 3.12 recommended. Needed for `tomllib` and the MCP SDK. |
| **~500 MB free disk** | Python deps + the embedding model (downloaded once). |
| **macOS or Linux** | Windows works via WSL. Apple Silicon fully supported (CPU/ONNX). |
| **Internet, first run only** | To download deps and the embedding model. Fully offline afterwards. |
| **git** | Required only for [team mode](#two-operating-modes-solo-vs-team). |
| **An MCP client** | e.g. Claude Code, to consume the corpus. Optional for CLI-only use. |

No GPU, no database server, no API keys.

Python deps (installed by setup): `fastembed`, `sqlite-vec`, `mcp` — see
`requirements.txt`.

## Quickstart

```bash
git clone <this-repo> && cd <this-repo>
./setup.sh            # creates .venv, installs deps, builds the index
```

Then, from an MCP client in this directory (Claude Code auto-loads `.mcp.json`):

```
/mcp                  # should list the "corpus" server + its 3 tools
```

Add your own docs:

```bash
cp ~/notes/*.md inbox/     # drop files in
make add                   # process inbox → local/, re-index
```

## How it works

- **`corpus/`** — one Markdown file per topic, with YAML frontmatter. **The
  canonical source of truth.** Humans edit these; agents only read; the files
  always win over the index.
- **`ingest.py`** — incrementally chunks each doc (heading-bounded,
  code-fence-atomic, breadcrumb-prefixed), embeds changed chunks locally, and
  writes the hybrid index. Refuses to run if the embedding model changed
  without `--rebuild`.
- **`server.py`** — a FastMCP **stdio** server exposing:
  - `search_specs(query, k)` — hybrid retrieval; returns cited passages.
  - `get_doc(path)` — a full topic file, on demand.
  - `list_docs()` — the table of contents.
- **`index/`** — the generated index. Gitignored, rebuildable any time.
- **`config.toml`** — paths, embedding model, and chunk sizes. Change behavior
  without touching code.

## Adding content — the inbox workflow

Content lives in two tiers, both indexed and searchable:

| Folder | Tier | Shared via git? | Purpose |
|--------|------|-----------------|---------|
| `corpus/` | **canonical** | yes — in **your own** (private) docs repo, never this engine repo | the shared source of truth |
| `local/`  | **local** | never (gitignored) | your private, "fine-tuned" set |

> This engine repo ships with an **empty** `corpus/`. See
> [`corpus/README.md`](./corpus/README.md) for the two ways to add your content.

1. **Drop** `.md` / `.txt` files into **`inbox/`**.
2. **`make add`** — each inbox file gets frontmatter and moves into `local/`,
   then the index rebuilds over both tiers. Usable by agents immediately,
   badged `[local]` so provenance is clear.
3. **Promote** when ready: **`make promote name=<doc>`** moves it `local/` →
   `corpus/` and flips its tier to canonical.

Nothing leaves your machine at any step. `corpus/` only becomes *shared* truth
once you commit and push it (team mode below).

## Two operating modes: solo vs team

The same engine runs two ways. **The only difference is where `corpus/` lives
and who can change it.**

### Solo / local-only (team of 1)

Everything is on your machine. `corpus/`, `local/`, and the index are all
local; there is no remote. You are the sole author. Great for personal use,
evaluation, or a private knowledge base.

- **Source of truth:** the `corpus/` folder on your disk.
- **Add/update:** edit files or use the inbox workflow; `make index`.
- **No git needed** (though committing locally still gives you history).

### Team / git as source of truth (team > 1)

The moment more than one person contributes, the source of truth must be
**git**, not any one laptop — otherwise you get conflicting copies. The shift
is small:

- **Source of truth:** the `corpus/` directory in a **git repository**;
  `main` is canonical truth.
- **Changes go through pull requests.** Same review flow as code. A
  `CODEOWNERS` file routes each domain to an accountable reviewer. Merging to
  `main` is the "becomes truth" gate.
- **Everyone pulls, then re-indexes locally:** `make sync` (= `git pull` +
  `ingest`). The **index is never shared** — each person rebuilds their own
  from the shared Markdown. This is intentional: no huge binary blobs or merge
  conflicts in git, and identical model + Markdown ⇒ equivalent index for
  everyone.
- **The `local/` tier stays private per person.** It's gitignored, so your
  personal notes never reach the shared repo until *you* `promote` them (which
  moves them into `corpus/`, where a commit/PR shares them).
- **Environments (dev/stg/prod) are metadata, not branches or copies** — see
  [ORGANIZATION.md](./ORGANIZATION.md).

### At a glance

| | Solo (local-only) | Team (git as truth) |
|---|---|---|
| Source of truth | `corpus/` on your disk | `corpus/` in git `main` |
| How truth changes | you edit files | pull request + merge |
| Index | local | local, rebuilt on `make sync` |
| Private notes | `local/` | `local/` (still private per person) |
| Sharing a doc | already local | `promote` → commit/push |
| git required | no | yes |

### Migrating solo → team

1. Move (or point) `corpus/` into your team's git repo — for a monorepo app,
   a top-level `corpus/` folder alongside the code is ideal (docs change in the
   same PR as code). See [Pointing at your own corpus](#pointing-the-engine-at-your-own-corpus).
2. Add a `CODEOWNERS` file and require PR review for `corpus/**`.
3. Teammates clone this engine, run `./setup.sh`, and `make sync`.
4. Keep the generated `index/` gitignored (already is).

> **CI/CD note (monorepo):** so docs-only edits don't trigger builds/deploys,
> add `paths-ignore: ['corpus/**']` to your code pipelines, and confirm deploys
> trigger on version tags rather than every push to `main`.

## Pointing the engine at your own corpus

By default the engine indexes the `corpus/` folder in this repo. To point it at
docs that live elsewhere (e.g. your app monorepo), create **`config.local.toml`**
(gitignored, per-machine):

```toml
[paths]
corpus = "/path/to/your/private-docs"   # absolute or relative to this repo
```

Then `make index`. Nothing else changes — the engine, the MCP tools, and the
`local/` tier all keep working; only the canonical source moves. This is how
the same engine serves any team's content.

## Using it from agents (MCP)

`.mcp.json` registers the server for this project, so Claude Code picks it up
automatically when launched from this directory. Verify with `/mcp`. Agents
then call:

- `search_specs("how do I roll back with a git tag", k=5)`
- `get_doc("rollback-procedure")`
- `list_docs()`

To use it from the Claude **desktop** app, add the same `command` + `args` to
`claude_desktop_config.json`.

## Organization scheme

How to structure the docs so the corpus stays coherent as it grows for years —
the 5-folder intent spine (`reference/how-to/explanation/decisions/records`),
the frontmatter contract, and how change is canonicalized — is documented in
**[ORGANIZATION.md](./ORGANIZATION.md)**. Templates for new docs, ADRs, and
records live in **[`templates/`](./templates)**.

## Command reference

```
make setup            Create venv, install deps, build the index
make add              Process inbox/ into local/ and re-index
make index            Incrementally re-index changed docs
make rebuild          Wipe and rebuild the whole index (after a model change)
make promote name=X   Promote local/X.md to canonical corpus/
make sync             git pull + re-index (team mode)
make clean            Remove the generated index
```

## Scaling & model upgrades

- **Better embeddings:** change `[embedding] model`/`dim` in `config.toml`
  (e.g. `bge-large-en-v1.5`, dim 1024), then `make rebuild`.
- **GPU throughput / big corpora:** move embedding to a local Ollama server —
  isolated behind the engine's embed calls.
- **Contextual retrieval:** prepend an LLM-generated one-line summary to each
  chunk at ingest time for a further recall boost.

The MCP interface stays identical through all of these — agents never notice.

## Repo layout

```
config.py / config.toml   Configuration (paths, model, chunk sizes)
ingest.py                 Incremental chunker + embedder
server.py                 MCP stdio server (search_specs / get_doc / list_docs)
tools/promote.py          local/ → corpus/ promotion
corpus/                   Your docs go here (ships empty; see corpus/README.md)
templates/                New-doc / ADR / record templates
ORGANIZATION.md           The corpus organization scheme
setup.sh / Makefile       Setup and common tasks
local/                    Private tier (gitignored)
inbox/                    Drop zone (gitignored)
index/                    Generated index (gitignored)
```
