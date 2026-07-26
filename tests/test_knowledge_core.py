"""Self-check for knowledge_core. Runs with pytest or plain python."""

import asyncio
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from knowledge_core import (  # noqa: E402
    KnowledgeLibrary,
    get_doc,
    list_docs,
    parse_frontmatter,
    register_knowledge_tools,
    rpc_handlers,
    split_sections,
    validate_library,
)

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples")

GOOD_DOC = """---
id: protocol.testproto
title: "Test protocol guide"
kind: protocol
summary: A guide used by the test suite.
protocol: testproto
keywords: [alpha, beta]
aliases: ["Alpha One"]
verified: verified
---

Preamble text.

## Overview
The overview.

## Details
The details with a snippet:

```yaml
- name: t
  address: "holding:0"
```
"""

BAD_DOC = """no frontmatter here"""

DUP_DOC = GOOD_DOC.replace("Test protocol guide", "Duplicate id doc")


def make_tree():
    root = tempfile.mkdtemp(prefix="knowledge-test-")
    os.makedirs(os.path.join(root, "protocols"))
    with open(os.path.join(root, "protocols", "good.md"), "w") as f:
        f.write(GOOD_DOC)
    with open(os.path.join(root, "protocols", "bad.md"), "w") as f:
        f.write(BAD_DOC)
    with open(os.path.join(root, "protocols", "dup.md"), "w") as f:
        f.write(DUP_DOC)
    return root


def test_parse_frontmatter():
    meta, body = parse_frontmatter(GOOD_DOC)
    assert meta["id"] == "protocol.testproto"
    assert body.startswith("Preamble")
    for broken in ("", "no front", "---\nid: x"):
        try:
            parse_frontmatter(broken)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


def test_split_sections():
    sections = split_sections(parse_frontmatter(GOOD_DOC)[1])
    assert [h for h, _ in sections] == ["", "Overview", "Details"]
    assert sections[1][1] == "The overview."


def test_load_tolerant_and_dedup():
    root = make_tree()
    try:
        lib = KnowledgeLibrary(root)
        assert list(lib.docs) == ["protocol.testproto"]
        assert len(lib.warnings) == 2  # bad.md unparsable + dup.md duplicate id
    finally:
        shutil.rmtree(root)


def test_vocab_validation():
    root = make_tree()
    try:
        lib = KnowledgeLibrary(root, vocab={"kind": {"device"}})
        assert lib.docs == {}
        assert any("kind" in w for w in lib.warnings)
    finally:
        shutil.rmtree(root)


def test_list_and_get():
    root = make_tree()
    try:
        lib = KnowledgeLibrary(root)
        out = list_docs(lib)
        assert out["count"] == 1 and out["docs"][0]["id"] == "protocol.testproto"
        assert list_docs(lib, query="alpha")["count"] == 1
        assert list_docs(lib, query="ALPHA ONE")["count"] == 1
        assert list_docs(lib, query="zzz")["count"] == 0
        assert "never invent" in list_docs(lib, query="zzz")["hint"]
        assert list_docs(lib, filters={"protocol": "testproto"})["count"] == 1
        assert list_docs(lib, filters={"protocol": "any"})["count"] == 1
        assert list_docs(lib, filters={"protocol": "other"})["count"] == 0

        doc = get_doc(lib, "protocol.testproto")
        assert doc["found"] and not doc["truncated"] and "## Overview" in doc["content"]
        assert doc["sections"] == ["Overview", "Details"]
        sec = get_doc(lib, "protocol.testproto", section="overview")
        assert sec["found"] and sec["content"] == "The overview."
        missing_sec = get_doc(lib, "protocol.testproto", section="nope")
        assert not missing_sec["found"] and "Available sections" in missing_sec["error"]
        missing = get_doc(lib, "protocol.testprot")
        assert not missing["found"] and "protocol.testproto" in missing["suggestions"]

        big = get_doc(lib, "protocol.testproto", max_chars=10)
        assert big["truncated"] and big["content"] == "The overview."
    finally:
        shutil.rmtree(root)


def test_rpc_handlers_conventions_and_serializable():
    root = make_tree()
    try:
        handlers = rpc_handlers(KnowledgeLibrary(root))
        results = [
            handlers["list"](),
            handlers["list"](query="alpha"),
            handlers["list"]({"query": "alpha", "protocol": "testproto"}),
            handlers["list"]("alpha"),
            handlers["list"](protocol="other"),
            handlers["get"](doc_id="protocol.testproto"),
            handlers["get"]({"doc_id": "protocol.testproto", "section": "Details"}),
            handlers["get"]("protocol.testproto", "Overview"),
            handlers["get"](doc_id="nope"),
            handlers["get"](),  # no args at all -> structured error
        ]
        for result in results:
            json.dumps(result)
        assert results[0]["count"] == 1
        assert results[3]["count"] == 1
        assert results[4]["count"] == 0
        assert results[7]["content"] == "The overview."
        assert results[9]["found"] is False
    finally:
        shutil.rmtree(root)


def test_rpc_handlers_ignore_the_routing_device_key():
    # Topic tools carry a device_key to address the gateway; the platform
    # strips it before dispatch. If one ever leaks through it must not reach
    # handle_list's catch-all metadata filters, where it matches no doc and
    # returns an empty library as a SUCCESS — the agent reads that as "this
    # app knows nothing" instead of retrying.
    root = make_tree()
    try:
        handlers = rpc_handlers(KnowledgeLibrary(root))
        assert handlers["list"](device_key=42) == handlers["list"]()
        assert handlers["list"]({"device_key": 42, "query": "alpha"})["count"] == 1
        assert handlers["list"](device_key=42, protocol="testproto")["count"] == 1
        assert (
            handlers["get"](doc_id="protocol.testproto", device_key=42)
            == handlers["get"](doc_id="protocol.testproto")
        )
    finally:
        shutil.rmtree(root)


def test_register_knowledge_tools():
    class FakeIronflock:
        def __init__(self, fail_topics=()):
            self.fail_topics = fail_topics
            self.registered = {}

        async def register_device_function(self, topic, handler):
            if topic in self.fail_topics:
                return None  # the real SDK returns None on failure
            self.registered[topic] = handler
            return object()

    root = make_tree()
    try:
        lib = KnowledgeLibrary(root)

        ok = FakeIronflock()
        failed = asyncio.run(register_knowledge_tools(ok, lib))
        assert failed == [] and sorted(ok.registered) == [
            "app_knowledge.get", "app_knowledge.list",
        ]
        # the registered endpoint actually serves
        assert ok.registered["app_knowledge.list"]()["count"] == 1

        reports = []

        async def report(msg, user_message=None):
            reports.append(msg)

        bad = FakeIronflock(fail_topics=("app_knowledge.get",))
        failed = asyncio.run(register_knowledge_tools(bad, lib, report=report))
        assert failed == ["app_knowledge.get"] and len(reports) == 1
    finally:
        shutil.rmtree(root)


def test_validate_library():
    root = make_tree()
    try:
        errors, warnings = validate_library(root)
        assert any("bad.md" in e for e in errors)
        assert any("dup.md" in e for e in errors)

        # snippet validator wired through
        def yaml_check(code):
            return ["boom"] if "holding:0" in code else []

        errors, _ = validate_library(root, snippet_validators={"yaml": yaml_check})
        assert any("yaml snippet: boom" in e for e in errors)
    finally:
        shutil.rmtree(root)


def test_example_doc_is_valid():
    errors, warnings = validate_library(EXAMPLE)
    assert errors == [], errors


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failures else 0)
