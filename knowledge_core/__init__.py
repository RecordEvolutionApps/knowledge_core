"""ironflock-knowledge-core: markdown knowledge libraries served to
IronFlock app AI agents as on-demand WAMP RPC tools (list/get)."""

__version__ = "1.0.0"

from .handlers import (
    DEFAULT_MAX_CHARS,
    get_doc,
    list_docs,
    rpc_handlers,
)
from .library import KnowledgeLibrary, parse_frontmatter, split_sections
from .register import DEFAULT_TOPICS, register_knowledge_tools
from .validate import fenced_blocks, validate_library

__all__ = [
    "DEFAULT_MAX_CHARS",
    "DEFAULT_TOPICS",
    "KnowledgeLibrary",
    "fenced_blocks",
    "get_doc",
    "list_docs",
    "parse_frontmatter",
    "register_knowledge_tools",
    "rpc_handlers",
    "split_sections",
    "validate_library",
]
