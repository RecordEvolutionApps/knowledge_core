"""RPC handlers over a KnowledgeLibrary.

`list_docs` / `get_doc` are the pure functions; `rpc_handlers` wraps them
into WAMP-callable endpoints that tolerate every calling convention
(kwargs, one positional dict, bare positional values) and NEVER raise —
an exception would surface to the AI agent as an opaque WAMP error, while
a structured dict tells it exactly how to recover.
"""

import difflib

DEFAULT_MAX_CHARS = 12000

# Frontmatter keys copied into compact list entries (when present).
LIST_ENTRY_KEYS = (
    "kind", "title", "vendor", "model", "equipment_type",
    "protocol", "drivers", "summary", "verified",
)

# Frontmatter keys searched by the free-text `query`.
SEARCH_KEYS = ("id", "title", "vendor", "model", "summary", "keywords", "aliases")

NO_MATCH_HINT = (
    "No knowledge doc matches. Ask the user for the device's register map or "
    "manual excerpt instead - never invent addresses."
)
LIST_HINT = (
    "Fetch a full document with the get tool (doc_id). Docs with "
    "verified=unverified contain addresses that MUST be verified against the "
    "device before trusting live values."
)


def _searchable(doc):
    parts = []
    for key in SEARCH_KEYS:
        value = doc["meta"].get(key)
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts).lower()


def _matches_filters(doc, filters):
    for key, wanted in (filters or {}).items():
        if wanted in (None, "", "any"):
            continue
        value = doc["meta"].get(key)
        wanted_l = str(wanted).lower()
        if isinstance(value, list):
            if wanted_l not in [str(v).lower() for v in value]:
                return False
        elif str(value).lower() != wanted_l:
            return False
    return True


def _matches_query(doc, query):
    if not query or not str(query).strip():
        return True
    haystack = _searchable(doc)
    return any(term in haystack for term in str(query).lower().split())


def _entry(doc):
    entry = {"id": doc["id"]}
    for key in LIST_ENTRY_KEYS:
        if key in doc["meta"]:
            entry[key] = doc["meta"][key]
    entry["chars"] = len(doc["body"])
    return entry


def list_docs(library, filters=None, query=None):
    """Compact catalog of matching docs: {count, docs, hint}."""
    library.load()
    matched = [
        _entry(doc)
        for doc in library.docs.values()
        if _matches_filters(doc, filters) and _matches_query(doc, query)
    ]
    matched.sort(key=lambda e: e["id"])
    return {
        "count": len(matched),
        "docs": matched,
        "hint": LIST_HINT if matched else NO_MATCH_HINT,
    }


def _suggestions(library, doc_id):
    ids = sorted(library.docs)
    close = difflib.get_close_matches(str(doc_id), ids, n=3, cutoff=0.4)
    needle = str(doc_id).lower()
    substr = [
        d["id"]
        for d in library.docs.values()
        if needle and (needle in d["id"].lower() or needle in _searchable(d))
    ]
    out = []
    for candidate in close + sorted(substr):
        if candidate not in out:
            out.append(candidate)
    return out[:5]


def get_doc(library, doc_id=None, section=None, max_chars=DEFAULT_MAX_CHARS):
    """One doc (or one `## ` section of it) as agent-consumable markdown."""
    library.load()
    doc = library.docs.get(str(doc_id or "").strip())
    if doc is None:
        suggestions = _suggestions(library, doc_id or "")
        hint = f" Closest matches: {', '.join(suggestions)}." if suggestions else ""
        return {
            "found": False,
            "error": f"No knowledge doc with id {str(doc_id)!r}.{hint}",
            "suggestions": suggestions,
            "available_ids": sorted(library.docs),
        }
    headings = [h for h, _ in doc["sections"] if h]
    base = {
        "found": True,
        "id": doc["id"],
        "title": doc["meta"].get("title", doc["id"]),
        "metadata": doc["meta"],
        "sections": headings,
    }
    if section:
        wanted = str(section).strip().lstrip("#").strip().lower()
        for heading, text in doc["sections"]:
            if heading.lower() == wanted:
                return {**base, "section": heading, "content": text, "truncated": False}
        return {
            **base,
            "found": False,
            "error": f"Doc {doc['id']!r} has no section {str(section)!r}. "
                     f"Available sections: {', '.join(headings)}.",
        }
    if len(doc["body"]) > max_chars:
        overview = next(
            (text for heading, text in doc["sections"] if heading.lower() == "overview"),
            doc["sections"][0][1] if doc["sections"] else "",
        )
        return {
            **base,
            "content": overview,
            "truncated": True,
            "error": "Document exceeds the response size limit; the Overview "
                     "section is shown. Fetch other sections individually via "
                     "the section parameter.",
        }
    return {**base, "content": doc["body"], "truncated": False}


def _coerce_kwargs(args, kwargs, positional=()):
    """Normalize WAMP call arguments into one kwargs dict.

    Accepts keyword args, a single positional dict, or bare positional
    values mapped onto `positional` names — the platform agent runtime's
    calling convention is not pinned down, so tolerate all of them.

    `device_key` is dropped: the agent must send it to address the call at a
    gateway and the platform strips it before dispatch, but a leaked one
    would land in handle_list's catch-all metadata filters and match no doc
    at all — an empty library reported as success rather than an error.
    """
    out = {}
    if len(args) == 1 and isinstance(args[0], dict):
        out.update(args[0])
    else:
        for name, value in zip(positional, args):
            out[name] = value
    for key, value in (kwargs or {}).items():
        out[key] = value
    out.pop("device_key", None)
    return out


def rpc_handlers(library):
    """-> {"list": callable, "get": callable} WAMP endpoints (never raise)."""

    def handle_list(*args, **kwargs):
        try:
            params = _coerce_kwargs(args, kwargs, positional=("query",))
            query = params.pop("query", None)
            filters = params.pop("filters", None)
            if not isinstance(filters, dict):
                filters = {}
            # remaining scalar params are treated as metadata filters
            filters.update({k: v for k, v in params.items() if not isinstance(v, (dict, list))})
            return list_docs(library, filters=filters, query=query)
        except Exception as e:  # never surface a raw WAMP error to the agent
            return {"count": 0, "docs": [], "error": f"knowledge library unavailable: {e}"}

    def handle_get(*args, **kwargs):
        try:
            params = _coerce_kwargs(args, kwargs, positional=("doc_id", "section"))
            return get_doc(library, doc_id=params.get("doc_id"), section=params.get("section"))
        except Exception as e:
            return {"found": False, "error": f"knowledge library unavailable: {e}"}

    return {"list": handle_list, "get": handle_get}
