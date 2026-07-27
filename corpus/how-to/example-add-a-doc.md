---
id: example-add-a-doc
title: "Example: adding a doc to the corpus"
type: how-to
status: active
owner: you
domain: [getting-started]
components: []
env: []
created: 2026-07-27
updated: 2026-07-27
review_by: 2027-07-27
supersedes: null
superseded_by: null
sources: []
---

# Example: adding a doc to the corpus

This is a sample document so the engine has something to index on first run.
**Delete it once you've added your own content.**

## Two ways to add content

1. Point `paths.corpus` in `config.local.toml` at your own private docs, then
   run `make index`.
2. Drop `.md` / `.txt` files into `inbox/` and run `make add`.

## How search works

Ask an agent a question; it calls `search_specs` and gets back the most
relevant sections with a `file:line` citation. Try: *"how do I add a doc to
the corpus?"* — this section should come back.
