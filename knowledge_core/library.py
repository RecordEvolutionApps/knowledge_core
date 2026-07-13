"""Markdown knowledge library: frontmatter-indexed docs for AI agents.

A knowledge doc is one markdown file with a YAML frontmatter block. The
frontmatter is the retrieval catalog (id, title, keywords, aliases, ...);
the body is what an agent fetches on demand. Loading is lazy, cached and
tolerant: a malformed doc is skipped with a warning, never an exception —
a broken doc must degrade the assistant, not the app embedding it.
"""

import os

import yaml


def parse_frontmatter(text):
    """Split a doc into (meta dict, body str).

    The frontmatter is a leading ``---`` ... ``---`` block containing YAML.
    Raises ValueError when the block is missing or not a YAML mapping.
    """
    if not text.startswith("---"):
        raise ValueError("missing frontmatter (file must start with ---)")
    first_break = text.find("\n")
    if first_break < 0 or text[:first_break].strip() != "---":
        raise ValueError("missing frontmatter (file must start with ---)")
    end = text.find("\n---", first_break)
    if end < 0:
        raise ValueError("unterminated frontmatter (no closing ---)")
    raw_meta = text[first_break + 1 : end]
    body_start = text.find("\n", end + 1)
    body = text[body_start + 1 :] if body_start >= 0 else ""
    meta = yaml.safe_load(raw_meta)
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a YAML mapping")
    return meta, body.strip("\n")


def split_sections(body):
    """Split a markdown body on ``## `` headings.

    Returns an ordered list of (heading, text) tuples; text before the first
    heading appears under the heading ``""``. Heading text excludes the
    ``## `` marker.
    """
    sections = []
    heading, lines = "", []
    for line in body.splitlines():
        if line.startswith("## "):
            if heading or lines:
                sections.append((heading, "\n".join(lines).strip("\n")))
            heading, lines = line[3:].strip(), []
        else:
            lines.append(line)
    if heading or lines:
        sections.append((heading, "\n".join(lines).strip("\n")))
    return sections


def _walk_md(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if name.endswith(".md"):
                yield os.path.join(dirpath, name)


class KnowledgeLibrary:
    """Loads and indexes the ``*.md`` docs under ``root`` (recursively).

    ``required_meta`` names the frontmatter keys every doc must carry.
    ``vocab`` optionally restricts values per frontmatter key, e.g.
    ``{"kind": {"device", "protocol", "guide"}}`` — list-valued fields are
    checked element-wise. Docs failing validation are skipped and recorded
    in ``warnings``. No I/O happens at construction; the first access loads
    and caches.
    """

    def __init__(self, root, required_meta=("id", "title", "kind", "summary"), vocab=None):
        self.root = root
        self.required_meta = tuple(required_meta)
        self.vocab = {k: set(v) for k, v in (vocab or {}).items()}
        self._docs = None
        self._warnings = None

    @property
    def docs(self):
        self.load()
        return self._docs

    @property
    def warnings(self):
        self.load()
        return list(self._warnings)

    def load(self, force=False):
        if self._docs is not None and not force:
            return self
        docs, warnings = {}, []
        if not os.path.isdir(self.root):
            self._docs, self._warnings = docs, [f"knowledge root not found: {self.root}"]
            return self
        for path in _walk_md(self.root):
            rel = os.path.relpath(path, self.root)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                meta, body = parse_frontmatter(text)
            except Exception as e:
                warnings.append(f"{rel}: {e}")
                continue
            problems = self._validate_meta(meta)
            if problems:
                warnings.append(f"{rel}: {'; '.join(problems)}")
                continue
            doc_id = str(meta["id"]).strip()
            if doc_id in docs:
                warnings.append(f"{rel}: duplicate id {doc_id!r} (also in {docs[doc_id]['path']})")
                continue
            docs[doc_id] = {
                "id": doc_id,
                "meta": meta,
                "body": body,
                "sections": split_sections(body),
                "path": rel,
            }
        self._docs, self._warnings = docs, warnings
        return self

    def _validate_meta(self, meta):
        problems = []
        for key in self.required_meta:
            value = meta.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                problems.append(f"missing required frontmatter key {key!r}")
        for key, allowed in self.vocab.items():
            if key not in meta:
                continue
            values = meta[key] if isinstance(meta[key], list) else [meta[key]]
            for value in values:
                if value not in allowed:
                    problems.append(
                        f"frontmatter {key}={value!r} not in allowed values {sorted(allowed)}"
                    )
        return problems
