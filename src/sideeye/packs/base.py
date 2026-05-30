"""Pack protocol.

A Pack is the unit of domain expertise in SideEye. It declares categories,
rules, optional templates, and optionally provides a rewriter. The engine
and TUI know nothing about a pack's domain — they just iterate its rules
and render its findings.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sideeye.models import Category, Finding, ScanResult, Severity

# --------------------------------------------------------------------------- #
# Rule
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PackRule:
    """A single detector inside a pack.

    Provide a `pattern` (compiled regex) for the common case, or a `detector`
    callable for anything more complex.
    """

    id: str
    category: str  # references one of the pack's category ids
    severity: Severity
    message: str
    suggestion: str | None = None
    pattern: re.Pattern[str] | None = None
    detector: Callable[[str], list[tuple[int, int, str]]] | None = None
    confidence: float = 0.82
    # If True, this rule only runs when pack.should_use_optional_rules(text) returns True.
    # Use for opt-in rules that produce too many false positives in the default mode.
    optional: bool = False
    # Optional question shown in the change log when the rewriter strips this
    # rule's match. Use for rules where the user likely had a real intent the
    # shortcut was approximating (jailbreaks, role overrides, "make it perfect")
    # so the user can write what they actually meant. Omit for rules with no
    # legitimate intent under the surface (injection, PII, exfiltration).
    revisit_hint: str | None = None

    def matches(self, text: str) -> list[tuple[int, int, str]]:
        if self.pattern is not None:
            return [(m.start(), m.end(), m.group(0)) for m in self.pattern.finditer(text)]
        if self.detector is not None:
            return self.detector(text)
        return []


# --------------------------------------------------------------------------- #
# Template (starter prompt or starter document for a pack)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Template:
    id: str
    title: str
    category: str   # free-form label, displayed dim next to the title
    description: str
    body: str       # the actual template text loaded into the editor


# --------------------------------------------------------------------------- #
# Pack protocol
# --------------------------------------------------------------------------- #

@runtime_checkable
class Pack(Protocol):
    """The contract every pack must satisfy.

    Subclass `BasePack` for the easy path. Implement the Protocol directly
    only if you need full control.
    """

    name: str          # short id, e.g. "prompt-safety"
    label: str         # human-readable, e.g. "Prompt Safety"
    description: str   # one-line pitch

    # File extensions this pack handles (for auto-detection from --file argument).
    file_extensions: tuple[str, ...]

    categories: list[Category]
    rules: list[PackRule]
    templates: list[Template]

    def detects(self, text: str) -> bool:
        """Should this pack auto-activate on this text? Used when no --pack flag."""
        ...

    def should_use_optional_rules(self, text: str) -> bool:
        """Are the `optional=True` rules in scope for this text?"""
        ...

    def rewrite(self, result: ScanResult) -> RewriteResult | None:
        """Produce a safer / better rewrite of the original text. Return None if
        this pack doesn't support rewriting."""
        ...

    def estimate_tokens(self, text: str) -> int:
        """Optional pack-specific token estimator. Falls back to a generic one."""
        ...


@dataclass
class RewriteResult:
    """Output of pack.rewrite()."""

    original: str
    rewritten: str
    diff_lines: list[str]   # unified diff lines, ready for display
    notes: list[str]        # human-readable list of changes made


# --------------------------------------------------------------------------- #
# BasePack — the convenient default implementation
# --------------------------------------------------------------------------- #

@dataclass
class BasePack:
    """Default Pack implementation. Subclass this and override what you need.

    Subclasses typically just set class attributes and override `rewrite()`.
    """

    name: str = "base"
    label: str = "Base"
    description: str = ""
    file_extensions: tuple[str, ...] = ()
    categories: list[Category] = field(default_factory=list)
    rules: list[PackRule] = field(default_factory=list)
    templates: list[Template] = field(default_factory=list)

    def detects(self, text: str) -> bool:
        return False

    def should_use_optional_rules(self, text: str) -> bool:
        return False

    def rewrite(self, result: ScanResult) -> RewriteResult | None:
        return None

    def estimate_tokens(self, text: str) -> int:
        if not text.strip():
            return 0
        words = len(text.split())
        chars = len(text)
        return max(1, int(words * 1.33), int(chars / 4))


# --------------------------------------------------------------------------- #
# scan(text, pack) — the engine
# --------------------------------------------------------------------------- #

def scan(text: str, pack: Pack, *, force_optional: bool = False) -> ScanResult:
    """Run a pack against text and return a ScanResult.

    `force_optional=True` arms `optional=True` rules unconditionally.
    Otherwise the pack's `should_use_optional_rules(text)` decides.
    """
    if not text or not text.strip():
        return ScanResult(
            original_prompt=text,
            overall_risk=Severity.LOW,
            token_count=0,
            pack=pack.name,
        )

    use_optional = force_optional or pack.should_use_optional_rules(text)

    findings: list[Finding] = []
    for rule in pack.rules:
        if rule.optional and not use_optional:
            continue
        for start, end, excerpt in rule.matches(text):
            stripped = excerpt.strip()
            # If the match was whitespace-only (e.g., trailing blank lines),
            # use a placeholder so the Finding constructor doesn't reject it.
            display_excerpt = stripped if stripped else "(whitespace)"
            findings.append(
                Finding(
                    id=rule.id,
                    category=rule.category,
                    severity=rule.severity,
                    span=(start, end),
                    excerpt=display_excerpt,
                    message=rule.message,
                    suggestion=rule.suggestion,
                    confidence=rule.confidence,
                )
            )

    # Deduplicate overlapping findings of the same rule at the same start.
    seen: set[str] = set()
    deduped: list[Finding] = []
    for f in findings:
        key = f"{f.id}:{f.span[0] if f.span else 0}"
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    # Aggregate severity = highest finding.
    if any(f.severity == Severity.CRITICAL for f in deduped):
        overall = Severity.CRITICAL
    elif any(f.severity == Severity.HIGH for f in deduped):
        overall = Severity.HIGH
    elif any(f.severity == Severity.MEDIUM for f in deduped):
        overall = Severity.MEDIUM
    elif deduped:
        overall = Severity.LOW
    else:
        overall = Severity.LOW

    tokens = pack.estimate_tokens(text)

    return ScanResult(
        original_prompt=text,
        findings=deduped,
        overall_risk=overall,
        token_count=tokens,
        pack=pack.name,
        context={"optional_rules_active": use_optional},
    )
