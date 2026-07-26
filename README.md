# ironflock-knowledge-core

A reusable knowledge library for IronFlock apps: ship distilled, hand-authored
markdown docs (protocol guides, device register maps, how-tos) inside your app
image and serve them to the platform AI agents as **on-demand WAMP RPC tools**
(`list` + `get`). Agents fetch only the documents a question needs — system
prompts stay small (the ai-template caps them at 5000 chars), knowledge scales
with files, not prompts.

This is retrieval-augmented generation without embeddings: the frontmatter of
each doc is the catalog, `list` does metadata filtering + keyword matching,
`get` returns the markdown. Deterministic, debuggable, zero infrastructure.
If a library ever outgrows keyword search, the `list` internals can switch to
embeddings without changing the tool contract agents see.

## Usage in an app

```
# requirements.txt
ironflock-knowledge-core @ git+https://github.com/RecordEvolutionApps/knowledge_core.git@v1.0.0
```

Put your docs in a directory that ships with the image (any layout of `*.md`
below one root works), then register the tools once the WAMP session is up —
in a collector app that is the adapter's `start_background` hook:

```python
from knowledge_core import KnowledgeLibrary, register_knowledge_tools

async def start_background(self, collector):
    from functools import partial
    library = KnowledgeLibrary(
        DOCS_DIR,
        vocab={"kind": {"device", "protocol", "guide"}},  # optional, per app
    )
    library.load()
    for warning in library.warnings:
        await collector.report_error(f"knowledge doc skipped: {warning}", level="warn")
    await register_knowledge_tools(
        collector.ironflock, library,
        report=partial(collector.report_error, level="warn"),
    )
```

`register_knowledge_tools` registers `app_knowledge.list` and
`app_knowledge.get` (override via `topics=`), returns the list of topics that
failed, and never raises. The registered URI is device- and app-scoped
(`{swarm}.{device}.{app}.{env}.{topic}`), so every app can use the same topic
names. **Requires `ironflock >= 1.5.3`** (`register_device_function`).

## The doc format

One markdown file per topic, YAML frontmatter + `## ` sections. See
[examples/example_doc.md](examples/example_doc.md) for the authoring template.

```yaml
---
id: device.vendor.model_slug     # REQUIRED, unique, stable; also protocol.<name> / guide.<topic>
title: "Human readable title"    # REQUIRED
kind: device                     # REQUIRED: device | protocol | guide (per-app vocab)
summary: >-                      # REQUIRED, <= 250 chars, shown in list results
  What this doc covers and whether its data is verified.
protocol: modbus                 # app-specific fields; anything here is filterable
drivers: [modbus-tcp]
vendor: "Vendor"
model: "Model family"
equipment_type: air_compressor
keywords: [lowercase, match, terms]
aliases: ["User-facing spellings", "Model 100"]
verified: unverified             # verified | field_tested | unverified
---
```

Authoring rules:

- **Distill, don't copy.** Write original prose and factual tables (register
  addresses, scaling, units). Never paste vendor-manual passages verbatim.
- **State the address base explicitly.** If the source material's base
  (0-based protocol vs 1-based document addresses) is unverified, show both
  readings, mark the doc `verified: unverified`, and tell the reader how to
  verify. Never silently pick one.
- **End device docs with a ready-to-paste config snippet** in a fenced
  ` ```yaml ` block — CI should parse every snippet with the app's real
  config parser (see Validation).
- Keep bodies under ~12k chars (warning) / 16k chars (hard error); split
  big topics into sections — `get` can fetch a single `## ` section.
- `keywords` and `aliases` are what make agent queries hit: include model
  numbers, product names, colloquial spellings.

## RPC contracts

`app_knowledge.list(protocol=..., equipment_type=..., query=...)` — any
scalar argument is a frontmatter filter (value `"any"` disables it); `query`
keyword-matches title/vendor/model/id/summary/keywords/aliases. Returns
`{count, docs: [{id, kind, title, vendor, model, equipment_type, protocol,
drivers, summary, verified, chars}], hint}`.

`app_knowledge.get(doc_id, section=None)` — returns `{found, id, title,
metadata, sections, content, truncated}`. Unknown ids return `{found: false,
error, suggestions, available_ids}` (difflib + substring matching) instead of
failing; oversized docs return the Overview plus the section list. Handlers
never raise — every path yields a structured, JSON-serializable dict an agent
can act on.

## ai-template tool blocks (copy-paste)

Add to each agent that should use the library (agents have separate contexts —
a delegate cannot see the main agent's tool results, so give it the tools too):

```yaml
    list_device_knowledge:
      description: >-
        Lists the app's built-in knowledge library: protocol guides and
        per-device register/tag maps. Filter by protocol or equipment_type,
        or pass a free-text query matching vendor/model/keywords. Returns
        compact entries with doc id, title, summary and a verified flag.
        List before answering device-specific questions; fetch full content
        with get_device_knowledge.
      topic: app_knowledge.list
      parameters:
        type: object
        properties:
          protocol:
            type: string
            description: Filter by protocol family. Omit or "any" for all.
          equipment_type:
            type: string
            description: Filter, e.g. air_compressor, energy_meter, plc.
          query:
            type: string
            description: Keywords matched against title, vendor, model, aliases.
        additionalProperties: false

    get_device_knowledge:
      description: >-
        Fetches one knowledge document (markdown) by doc id from
        list_device_knowledge: connection defaults, register/tag maps, a
        ready-to-paste config snippet, pitfalls and verification caveats.
        Prefer doc content over memory and repeat its warnings. For long
        docs pass section to fetch a single "## " section. Unknown ids
        return closest-match suggestions instead of failing.
      topic: app_knowledge.get
      parameters:
        type: object
        properties:
          doc_id:
            type: string
            description: Doc id from list_device_knowledge, e.g. protocol.s7.
          section:
            type: string
            description: Optional "## " heading to fetch only that section.
        required: [doc_id]
        additionalProperties: false
```

Prompt guidance for the agents: "Before answering vendor- or model-specific
questions, call list_device_knowledge and fetch matching docs with
get_device_knowledge. Prefer doc content over your own memory and repeat the
doc's verification caveats. If no doc matches, say so and work only from
user-supplied material." Budget one or two extra `max_iterations` for the
list→get round-trips.

## Validation (CI)

```python
from knowledge_core import validate_library

errors, warnings = validate_library(
    DOCS_DIR,
    vocab={"kind": {"device", "protocol", "guide"}},
    snippet_validators={"yaml": my_app_snippet_check},  # -> [error strings]
)
```

Wire this into a small check script that exits non-zero on `errors` — every
fenced snippet in every doc then goes through your app's real parser on every
change. See the plc_collector's `collector/check_knowledge.py` for a worked
example.

## Dev tasks

```bash
just setup          # create .venv with the package (editable) + test deps
just test           # run pytest (uses .venv if present)
just test -k rpc    # run a subset (args pass through to pytest)
just release 1.1.0  # bump version, test, commit, tag, push (main only, clean tree)
just release-patch  # auto-bump the patch version and release it
```

## Releasing a new version

Same model as `collector_core`: no PyPI package — apps install from this Git
repo and pin a tag. A release is a version bump on `main` plus a matching tag:

1. Judge semver by the public API (`KnowledgeLibrary`, `list_docs`/`get_doc`
   response shapes, `register_knowledge_tools`, `validate_library`) and the
   doc-format contract (required frontmatter keys).
2. Run `just release X.Y.Z` (or `just release-patch`). It bumps `version` in
   `pyproject.toml` and `__version__` in `knowledge_core/__init__.py`, runs
   the tests, commits on `main`, tags `vX.Y.Z` and pushes with `--tags` —
   refusing to run off `main`, on a dirty tree, or onto an existing tag. Keep
   the git tag and the `pyproject.toml` version identical.
3. Re-pin consuming apps' `requirements.txt` when they are ready.

SDK note: this library never imports `ironflock`; the handle is injected.
Apps must pin **`ironflock >= 1.5.3`** for `register_device_function`.

## LICENSE

Copyright 2026 Record Evolution GmbH
All rights reserved
