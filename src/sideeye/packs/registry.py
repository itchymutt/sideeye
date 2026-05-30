"""Pack registry.

Built-in packs live here. Future: load third-party packs via entry points.
"""

from __future__ import annotations

from pathlib import Path

from sideeye.packs.base import Pack
from sideeye.packs.markdown import MarkdownPack
from sideeye.packs.personal_info import PersonalInfoPack
from sideeye.packs.prompt_safety import PromptSafetyPack

BUILTIN_PACKS: dict[str, Pack] = {
    "prompt-safety": PromptSafetyPack(),
    "markdown": MarkdownPack(),
    "personal-info": PersonalInfoPack(),
}


DEFAULT_PACK = "prompt-safety"


def list_packs() -> list[Pack]:
    """All registered packs, default first."""
    default = BUILTIN_PACKS[DEFAULT_PACK]
    rest = [p for name, p in BUILTIN_PACKS.items() if name != DEFAULT_PACK]
    return [default, *rest]


def get_pack(name: str) -> Pack:
    """Look up a pack by name. Raises KeyError if unknown."""
    if name in BUILTIN_PACKS:
        return BUILTIN_PACKS[name]
    available = ", ".join(BUILTIN_PACKS.keys())
    raise KeyError(f"Unknown pack: {name!r}. Available: {available}")


def pack_for_file(path: Path) -> Pack | None:
    """Best-effort pack selection for a file. Returns None if no match."""
    suffix = path.suffix.lower()
    for pack in BUILTIN_PACKS.values():
        if suffix in pack.file_extensions:
            return pack
    return None


def pack_for_text(text: str) -> Pack:
    """Auto-detect the best pack for a piece of text. Always returns something
    (falls back to the default pack)."""
    # Ask each pack — but the default pack wins ties.
    default = BUILTIN_PACKS[DEFAULT_PACK]
    if default.detects(text):
        return default
    for pack in BUILTIN_PACKS.values():
        if pack is default:
            continue
        if pack.detects(text):
            return pack
    return default
