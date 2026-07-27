# Corpus organization scheme

How the source-of-truth documents are structured. This scheme is designed so
the **top level never needs reorganizing**, no matter how much the underlying
application changes. It is engine-independent: any RAG can consume it, because
it is just Markdown + YAML frontmatter.

## Two axes

**1. Folders — by document *intent and lifecycle* (stable for years).**
Features and services churn; the *kinds* of knowledge a team needs do not.

| Folder | What it holds | Lifecycle |
|--------|---------------|-----------|
| `reference/`   | Facts about how things are **now** — config, inventories, metric/API refs, standards & policies. | Mutable; always reflects the present. |
| `how-to/`      | Task recipes & operational runbooks ("roll back", "set up Meta"). | Mutable. |
| `explanation/` | How & why it works — architecture, concepts, background. | Mutable. |
| `decisions/`   | ADRs — why we chose X. Numbered. | **Append-only, immutable.** |
| `records/`     | Point-in-time snapshots — postmortems, investigations, migration/cleanup logs. | **Append-only, immutable.** |

Start flat inside each folder. Only add domain subfolders (e.g.
`reference/observability/`) once a folder exceeds ~15–20 files.

**2. Tags — by domain / component / environment (the volatile axis).**
Everything that changes with the product lives in frontmatter tags, never in
the folder structure. When the app changes, you change a tag — you never move
folders.

## Environments are metadata, not structure

There is **one** source of truth. Do **not** split by environment
(no `dev/ stg/ prod/` folders, no branch-per-environment, no copies).
Environment differences are captured **inside** a doc via `env: [prod]` or a
section. Three copies = three things to drift out of sync.

## Frontmatter contract

Every doc carries this schema. The fields marked ★ are what make retrieval
trustworthy (freshness, status filtering, supersession).

```yaml
---
id: deploy-runbook              # ★ stable permalink — NEVER changes, even on rename
title: Deployment Runbook
type: how-to                    # reference | how-to | explanation | decision | record
status: active                  # ★ draft | active | deprecated | superseded
owner: platform-team
domain: [deployment, incident-response]   # facet tags (volatile axis)
components: [service-a, database]
env: [prod]                     # metadata, not structure
created: 2026-07-20
updated: 2026-07-24              # ★ freshness
review_by: 2026-10-24           # ★ staleness signal
supersedes: null                # ★ id of the doc this replaces
superseded_by: null             # ★ id, once deprecated
sources: []                     # links to code / PRs / dashboards
---
```

## How change is canonicalized

The rule that prevents conflicting truths: **one fact has exactly one current
home, plus an immutable trail of why it changed.**

1. **Significant decision?** Write a *new* ADR in `decisions/`. Never edit an
   accepted one — if it reverses a prior decision, set `supersedes` (and the
   old one's `superseded_by`, flipping it to `status: superseded`).
2. **Update the affected `reference/how-to/explanation` doc in place** to
   describe the new present. Bump `updated`. Git history holds old versions.
3. **Replacing a whole doc?** Mark the old `status: deprecated`, set
   `superseded_by`, add the new with `supersedes`.
4. **Deprecate, don't delete.** The RAG hides deprecated docs from default
   results but keeps them for provenance. Delete only true noise.

*Living docs are edited; decisions & records are only appended.*

## Naming

- Files: `kebab-case.md`, descriptive, stable. Don't encode env/version in the
  filename — that's frontmatter.
- ADRs: numbered — `decisions/0007-adopt-event-bus.md`.
- Records: date-prefixed — `records/2026-07-checkout-outage.md`.
