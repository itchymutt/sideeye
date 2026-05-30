"""Rewrite/remix engine.

Thin dispatcher: looks up the pack that produced the scan, asks it to rewrite.
The actual rewrite logic lives in each pack.

Backwards-compatible: `safe_remix(result)` still works. If the result was
produced by the prompt-safety pack (or has no pack set), the original
deterministic prompt-rewriter runs.
"""

from __future__ import annotations

from typing import NamedTuple

from sideeye.models import ScanResult
from sideeye.packs.base import Pack, RewriteResult
from sideeye.packs.registry import BUILTIN_PACKS, DEFAULT_PACK, get_pack


class RemixResult(NamedTuple):
    """Legacy tuple shape. New code should use packs.base.RewriteResult."""

    original: str
    remixed: str
    diff_lines: list[str]
    notes: list[str]


def safe_remix(result: ScanResult, designer_mode: bool = False) -> RemixResult:
    """Rewrite the scanned text using the pack that produced this scan.

    For backwards compatibility with the old `safe_remix(scan_result)` callers.
    Always returns a RemixResult, even when the pack doesn't support rewriting
    (in that case, the rewritten text equals the original).
    """
    pack_name = result.pack or DEFAULT_PACK
    try:
        pack: Pack = get_pack(pack_name)
    except KeyError:
        pack = BUILTIN_PACKS[DEFAULT_PACK]

    # Old callers expected `designer_mode` to influence the prompt-safety rewriter.
    if designer_mode:
        result.context["designer_mode"] = True

    rewrite = pack.rewrite(result)
    if rewrite is None:
        return RemixResult(
            original=result.original_prompt,
            remixed=result.original_prompt,
            diff_lines=[],
            notes=[f"The {pack.label} pack does not support rewriting."],
        )

    return RemixResult(
        original=rewrite.original,
        remixed=rewrite.rewritten,
        diff_lines=rewrite.diff_lines,
        notes=rewrite.notes,
    )


def rewrite(result: ScanResult) -> RewriteResult | None:
    """Generic rewrite. Returns the pack's RewriteResult, or None if unsupported."""
    pack_name = result.pack or DEFAULT_PACK
    pack = get_pack(pack_name) if pack_name in BUILTIN_PACKS else BUILTIN_PACKS[DEFAULT_PACK]
    return pack.rewrite(result)
