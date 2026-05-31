"""Pack registry.

Built-in packs ship with sideeye. Third-party packs install themselves via
the `sideeye.packs` entry-point group:

    # In a third-party package's pyproject.toml:
    [project.entry-points."sideeye.packs"]
    skill-lint = "skillet.packs.skill_lint:SkillLintPack"

The entry point's value is `module.path:ClassName`. The class is instantiated
with no arguments; if it needs configuration, expose constructor parameters
with defaults.

Builtin packs win conflicts with third-party packs of the same name (the
user has to explicitly override by renaming their pack).
"""

from __future__ import annotations

import logging
from pathlib import Path

try:
    from importlib.metadata import entry_points
except ImportError:  # pragma: no cover — Python 3.8 only
    entry_points = None  # type: ignore[assignment]

from sideeye.packs.base import Pack
from sideeye.packs.markdown import MarkdownPack
from sideeye.packs.personal_info import PersonalInfoPack
from sideeye.packs.prompt_safety import PromptSafetyPack

log = logging.getLogger(__name__)


BUILTIN_PACKS: dict[str, Pack] = {
    "prompt-safety": PromptSafetyPack(),
    "markdown": MarkdownPack(),
    "personal-info": PersonalInfoPack(),
}


DEFAULT_PACK = "prompt-safety"

# Third-party packs, loaded on demand via entry points. Cached after first load.
_THIRD_PARTY_PACKS: dict[str, Pack] | None = None


def _load_third_party_packs() -> dict[str, Pack]:
    """Discover packs registered under the `sideeye.packs` entry-point group.

    Errors during a single pack's load (import failure, instantiation failure,
    not implementing the Pack protocol) are logged and skipped. One bad pack
    must not block the others from loading.
    """
    discovered: dict[str, Pack] = {}
    if entry_points is None:
        return discovered

    try:
        eps = entry_points(group="sideeye.packs")
    except Exception as e:  # pragma: no cover — defensive
        log.warning("could not enumerate sideeye.packs entry points: %s", e)
        return discovered

    for ep in eps:
        if ep.name in BUILTIN_PACKS:
            log.warning(
                "third-party pack %r shadows a builtin; builtin wins. "
                "Rename the third-party pack to use it.",
                ep.name,
            )
            continue
        try:
            cls = ep.load()
            pack = cls()
        except Exception as e:
            log.warning("failed to load pack %r from %s: %s", ep.name, ep.value, e)
            continue
        if not isinstance(pack, Pack):
            log.warning(
                "pack %r does not implement the Pack protocol (got %s); skipping",
                ep.name, type(pack).__name__,
            )
            continue
        discovered[ep.name] = pack
    return discovered


def _all_packs() -> dict[str, Pack]:
    """Builtins plus any discovered third-party packs."""
    global _THIRD_PARTY_PACKS
    if _THIRD_PARTY_PACKS is None:
        _THIRD_PARTY_PACKS = _load_third_party_packs()
    # Builtins win by appearing first in the merged dict
    return {**_THIRD_PARTY_PACKS, **BUILTIN_PACKS}


def reload_third_party_packs() -> None:
    """Force a re-scan of entry points. Useful in tests and long-running sessions."""
    global _THIRD_PARTY_PACKS
    _THIRD_PARTY_PACKS = None


def list_packs() -> list[Pack]:
    """All registered packs (builtins + third-party), default first."""
    all_packs = _all_packs()
    default = all_packs[DEFAULT_PACK]
    rest = [p for name, p in all_packs.items() if name != DEFAULT_PACK]
    return [default, *rest]


def get_pack(name: str) -> Pack:
    """Look up a pack by name. Raises KeyError if unknown."""
    all_packs = _all_packs()
    if name in all_packs:
        return all_packs[name]
    available = ", ".join(sorted(all_packs.keys()))
    raise KeyError(f"Unknown pack: {name!r}. Available: {available}")


def pack_for_file(path: Path) -> Pack | None:
    """Best-effort pack selection for a file. Returns None if no match."""
    suffix = path.suffix.lower()
    for pack in _all_packs().values():
        if suffix in pack.file_extensions:
            return pack
    return None


def pack_for_text(text: str) -> Pack:
    """Auto-detect the best pack for a piece of text. Always returns something
    (falls back to the default pack)."""
    all_packs = _all_packs()
    # Ask each pack — but the default pack wins ties.
    default = all_packs[DEFAULT_PACK]
    if default.detects(text):
        return default
    for pack in all_packs.values():
        if pack is default:
            continue
        if pack.detects(text):
            return pack
    return default
