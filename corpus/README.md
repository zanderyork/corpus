# corpus/ — your canonical docs go here

**This folder ships empty on purpose.** This repository is the *engine* only —
it contains **no content**. You populate the corpus with your **own** docs, in
one of two ways:

1. **Point the engine at your private docs** (recommended for teams). In
   `config.local.toml` set `paths.corpus` to a checkout of your own private
   docs repo — e.g. a `corpus/` folder in your app's repo:
   ```toml
   [paths]
   corpus = "/path/to/your/private-docs"
   ```
   Then `make index`. Your content never touches this public engine repo.

2. **Add docs locally.** Drop `.md` / `.txt` files into `inbox/`, run
   `make add`, and they land in the private `local/` tier (gitignored).
   Promote to canonical with `make promote name=<doc>`.

> ⚠️ **Do not commit private/internal docs into a clone of this public engine
> repo.** Keep your content in your own (private) version control.

## How to organize what you put here

Use the intent-based buckets below (details in
[../ORGANIZATION.md](../ORGANIZATION.md)); templates are in
[../templates/](../templates):

| Folder | Holds |
|--------|-------|
| `reference/`   | Current-state facts — config, inventories, API/metric refs, standards. |
| `how-to/`      | Task recipes & runbooks. |
| `explanation/` | Concepts, architecture, the "why". |
| `decisions/`   | ADRs (append-only, immutable). |
| `records/`     | Postmortems, investigations, migration logs (append-only). |

Environment differences (dev/stg/prod) go in a doc's frontmatter `env:` tag —
never in separate folders or branches.

The engine indexes these folders recursively, so `reference/foo.md` and
`how-to/bar.md` are both picked up automatically.
