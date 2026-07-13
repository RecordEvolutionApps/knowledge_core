"""CI-grade validation of a knowledge library.

`KnowledgeLibrary.load` is deliberately tolerant (skip + warn); this module
is the strict counterpart for check scripts: every load warning is an
error, size caps are enforced, and fenced code blocks are run through
app-supplied validators (e.g. the PLC app parses every ```yaml block with
its real datapoint-spec parser).
"""

import re

from .library import KnowledgeLibrary

DEFAULT_CAPS = {
    "summary": 250,        # chars; keeps list entries compact
    "body_target": 12000,  # chars; soft cap -> warning
    "body_hard": 16000,    # chars; hard cap -> error
}

_FENCE = re.compile(r"^```(\w+)\s*$(.*?)^```\s*$", re.MULTILINE | re.DOTALL)


def fenced_blocks(body):
    """-> [(language, code), ...] for every fenced block in a markdown body."""
    return [(m.group(1).lower(), m.group(2).strip("\n")) for m in _FENCE.finditer(body)]


def validate_library(root, required_meta=("id", "title", "kind", "summary"),
                     vocab=None, snippet_validators=None, caps=None):
    """-> (errors, warnings): lists of strings; empty errors = valid.

    snippet_validators: {"yaml": fn, ...} — fn(code) returns a list of error
    strings for one fenced block of that language.
    """
    caps = {**DEFAULT_CAPS, **(caps or {})}
    library = KnowledgeLibrary(root, required_meta=required_meta, vocab=vocab).load(force=True)
    errors = [f"load: {w}" for w in library.warnings]
    warnings = []
    for doc_id, doc in sorted(library.docs.items()):
        where = doc["path"]
        summary = str(doc["meta"].get("summary", ""))
        if len(summary) > caps["summary"]:
            errors.append(f"{where}: summary is {len(summary)} chars (cap {caps['summary']})")
        size = len(doc["body"])
        if size > caps["body_hard"]:
            errors.append(f"{where}: body is {size} chars (hard cap {caps['body_hard']})")
        elif size > caps["body_target"]:
            warnings.append(f"{where}: body is {size} chars (target {caps['body_target']})")
        for lang, code in fenced_blocks(doc["body"]):
            check = (snippet_validators or {}).get(lang)
            if check is None:
                continue
            try:
                problems = check(code) or []
            except Exception as e:
                problems = [f"validator crashed: {e}"]
            errors.extend(f"{where}: {lang} snippet: {p}" for p in problems)
    if not library.docs:
        errors.append(f"no docs found under {root}")
    return errors, warnings
