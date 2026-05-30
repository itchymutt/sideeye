"""Rule packs for SideEye.

A Pack is a self-contained set of rules, categories, optional templates, and
an optional rewriter. Packs are how SideEye stays generic: the engine and TUI
know nothing about prompts, markdown, email, or any specific domain.

Built-in packs:
- `prompt_safety` — the original SideEye rules (LLM prompt and trace safety)
- `markdown` — basic Markdown style and consistency checks

To register a new pack, add it to `BUILTIN_PACKS` in `registry.py`.
"""

from sideeye.packs.base import Pack, PackRule, Template
from sideeye.packs.registry import (
    BUILTIN_PACKS,
    DEFAULT_PACK,
    get_pack,
    list_packs,
    pack_for_file,
    pack_for_text,
)

__all__ = [
    "Pack",
    "PackRule",
    "Template",
    "BUILTIN_PACKS",
    "DEFAULT_PACK",
    "get_pack",
    "list_packs",
    "pack_for_file",
    "pack_for_text",
]
