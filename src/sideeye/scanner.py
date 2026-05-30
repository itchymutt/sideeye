"""Scanner orchestrator.

Thin wrapper around the pack engine. The actual rules live in packs.
This module keeps the legacy `scan_prompt` / `scan_trace` API so existing
code continues to work, and adds a generic `scan_text` for new code.
"""

from __future__ import annotations

import json
from typing import Any

from sideeye.models import ScanResult
from sideeye.packs.base import Pack, scan
from sideeye.packs.registry import BUILTIN_PACKS, DEFAULT_PACK, get_pack

# --------------------------------------------------------------------------- #
# Generic API
# --------------------------------------------------------------------------- #

def scan_text(
    text: str,
    pack: Pack | str | None = None,
    *,
    force_optional: bool = False,
) -> ScanResult:
    """Run a pack against text. The new, generic entry point.

    `pack` can be a Pack instance, a pack name string, or None (uses default).
    `force_optional=True` arms optional rules regardless of pack's own logic.
    """
    if pack is None:
        pack = BUILTIN_PACKS[DEFAULT_PACK]
    elif isinstance(pack, str):
        pack = get_pack(pack)
    return scan(text, pack, force_optional=force_optional)


# --------------------------------------------------------------------------- #
# Legacy API (kept for backwards compatibility)
# --------------------------------------------------------------------------- #

def scan_prompt(text: str, designer_mode: bool = False) -> ScanResult:
    """Legacy entry point. Equivalent to scanning with the prompt-safety pack.

    `designer_mode=True` forces optional (designer-only) rules on.
    """
    return scan_text(text, pack="prompt-safety", force_optional=designer_mode)


def scan_trace(trace_text: str, designer_mode: bool = False) -> ScanResult:
    """Extract content from a JSON/JSONL agent trace and scan with prompt-safety."""
    contents: list[str] = [trace_text]

    try:
        if trace_text.strip().startswith(("{", "[")):
            data: Any = json.loads(trace_text)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        for key in ("content", "text", "message", "prompt"):
                            if key in item and isinstance(item[key], str):
                                contents.append(item[key])
            elif isinstance(data, dict):
                for key in ("messages", "steps", "trace", "history"):
                    if key in data and isinstance(data[key], list):
                        for msg in data[key]:
                            if isinstance(msg, dict):
                                for k in ("content", "text"):
                                    if k in msg and isinstance(msg[k], str):
                                        contents.append(msg[k])
    except (json.JSONDecodeError, TypeError, KeyError):
        pass

    combined = "\n\n".join(c for c in contents if c and c.strip())
    result = scan_prompt(combined, designer_mode=designer_mode)
    result.original_prompt = trace_text
    return result


# --------------------------------------------------------------------------- #
# Legacy rule registration (kept for extension code in the wild)
# --------------------------------------------------------------------------- #

def register_rule(rule: Any) -> None:
    """DEPRECATED. Add rules to a pack instead.

    Kept as a no-op + warning for compatibility. New code should subclass
    `BasePack` or extend an existing pack's `rules` list.
    """
    import warnings
    warnings.warn(
        "register_rule() is deprecated. Add rules to a Pack instead. "
        "See sideeye/packs/prompt_safety.py for an example.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Best-effort: if the caller passed a Rule-like object with id/category/level/message,
    # convert to a PackRule and append to the prompt-safety pack.
    try:
        from sideeye.packs.base import PackRule
        from sideeye.packs.registry import BUILTIN_PACKS

        pr = PackRule(
            id=rule.id,
            category=getattr(rule, "category", "misc"),
            severity=getattr(rule, "level", None) or rule.severity,
            message=rule.message,
            suggestion=getattr(rule, "suggestion", None),
            pattern=getattr(rule, "pattern", None),
            detector=getattr(rule, "detector", None),
            confidence=getattr(rule, "confidence", 0.82),
            optional=getattr(rule, "designer_only", False) or getattr(rule, "optional", False),
        )
        # Category may be a RiskCategory enum
        if hasattr(pr.category, "value"):
            object.__setattr__(pr, "category", pr.category.value)
        BUILTIN_PACKS[DEFAULT_PACK].rules.append(pr)
    except Exception:
        pass


# Re-export for legacy code that imported the Rule dataclass from scanner.
from sideeye.packs.base import PackRule as Rule  # noqa: E402,F401
