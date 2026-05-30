"""Generic data models for SideEye.

The vocabulary is intentionally domain-neutral so that packs can ship rules
for any kind of text (prompts, markdown, email, commit messages, etc.).

Backwards-compatible aliases at the bottom of the file:
- `RiskLevel` is now an alias for `Severity`
- `RiskCategory` is the historical prompt-safety category enum, kept as-is
- Old code that imports `RiskLevel.CRITICAL` etc. continues to work.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# --------------------------------------------------------------------------- #
# Severity (generic)
# --------------------------------------------------------------------------- #

class Severity(str, Enum):
    """Severity of a finding. Generic across all packs.

    Ordering: LOW < MEDIUM < HIGH < CRITICAL. Use `.rank` for comparisons.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {self.LOW: 1, self.MEDIUM: 2, self.HIGH: 3, self.CRITICAL: 4}[self]

    @property
    def color(self) -> str:
        """Rich/Textual color for terminal rendering."""
        return {
            self.LOW: "green",
            self.MEDIUM: "yellow",
            self.HIGH: "orange1",
            self.CRITICAL: "red",
        }[self]

    @property
    def glyph(self) -> str:
        return {self.LOW: "·", self.MEDIUM: "▴", self.HIGH: "▲", self.CRITICAL: "■"}[self]


# Backwards-compatible alias for existing code paths.
RiskLevel = Severity


# --------------------------------------------------------------------------- #
# Category
# --------------------------------------------------------------------------- #

class Category(BaseModel):
    """A grouping of related findings. Packs define their own categories.

    Use a stable, machine-friendly `id` (snake_case). The `label` is what users
    see in the UI.
    """

    id: str = Field(..., min_length=1, description="Stable snake_case identifier")
    label: str = Field(..., min_length=1, description="Human-readable label")
    description: str | None = None


# Historical prompt-safety categories. Kept as an enum so that old imports work
# (`from sideeye.models import RiskCategory`) and so the prompt-safety pack can
# reference them by name. New packs should declare their own `Category` objects.
class RiskCategory(str, Enum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    PII_LEAK = "pii_leak"
    DATA_EXFILTRATION = "data_exfiltration"
    OVERCONFIDENCE = "overconfidence"
    CREATIVE_DRIFT = "creative_drift"
    COPYRIGHT_RISK = "copyright_risk"
    BRAND_IMPERSONATION = "brand_impersonation"
    STRUCTURED_INJECTION = "structured_injection"
    TOKEN_BOMB = "token_bomb"
    ROLE_ESCALATION = "role_escalation"
    VAGUE_DANGER = "vague_danger"


# --------------------------------------------------------------------------- #
# Finding
# --------------------------------------------------------------------------- #

class Finding(BaseModel):
    """A single detected issue in the scanned text."""

    id: str = Field(..., description="Stable identifier for the rule that fired")
    # Category as a string id (snake_case). Pack-defined.
    # When a RiskCategory enum is passed, its `.value` is used.
    category: str = Field(..., min_length=1)
    severity: Severity
    span: tuple[int, int] | None = Field(
        default=None, description="Character offsets (start, end) in original text"
    )
    excerpt: str = Field(..., min_length=1, description="The offending snippet")
    message: str = Field(..., description="Plain-language explanation")
    suggestion: str | None = Field(default=None, description="Actionable fix")
    confidence: float = Field(0.85, ge=0.0, le=1.0)

    # --- Backwards-compatibility shims ---

    @property
    def level(self) -> Severity:
        """Alias for `severity`. Old code uses `.level`."""
        return self.severity

    @property
    def short_category(self) -> str:
        return self.category.replace("_", " ").title()

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, v: Any) -> str:
        # Accept enum values, plain strings, anything stringable with a `.value`.
        if isinstance(v, str):
            return v
        if hasattr(v, "value"):
            return str(v.value)
        return str(v)

    @field_validator("severity", mode="before")
    @classmethod
    def _accept_level_alias(cls, v: Any) -> Any:
        # Allow `level=` to be passed in older code paths.
        return v


# --------------------------------------------------------------------------- #
# ScanResult
# --------------------------------------------------------------------------- #

class ScanResult(BaseModel):
    """Complete output of scanning some text with a pack's rules."""

    original_prompt: str = Field(..., description="The original input text")
    findings: list[Finding] = Field(default_factory=list)
    overall_risk: Severity = Severity.LOW
    token_count: int = Field(0, ge=0)
    # Pack name that produced this result. None for legacy/unbound results.
    pack: str | None = None
    # Free-form pack-specific metadata. Replaces the old `is_designer_prompt` bool.
    # Packs can stash anything here; UI uses it to render badges or hints.
    context: dict[str, Any] = Field(default_factory=dict)
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Populated after a rewrite
    remix_suggestion: str | None = None
    remix_diff: list[str] | None = None

    @field_validator("findings")
    @classmethod
    def _sort_findings(cls, v: list[Finding]) -> list[Finding]:
        order = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
        }
        return sorted(v, key=lambda f: (order[f.severity], f.category))

    @property
    def has_critical(self) -> bool:
        return any(f.severity == Severity.CRITICAL for f in self.findings)

    @property
    def has_high_or_worse(self) -> bool:
        return any(f.severity.rank >= Severity.HIGH.rank for f in self.findings)

    @property
    def finding_counts(self) -> dict[Severity, int]:
        counts: dict[Severity, int] = {s: 0 for s in Severity}
        for f in self.findings:
            counts[f.severity] += 1
        return counts

    # --- Backwards-compatibility shims ---

    @property
    def is_designer_prompt(self) -> bool:
        """Legacy field. True when designer/optional rules are active for this scan.

        Backed by context['designer_mode'] (explicit) or context['optional_rules_active']
        (auto-detected). Either implies the prompt-safety pack's optional rules ran.
        """
        return bool(
            self.context.get("designer_mode", False)
            or self.context.get("optional_rules_active", False)
        )

    @is_designer_prompt.setter
    def is_designer_prompt(self, value: bool) -> None:
        self.context["designer_mode"] = bool(value)

    def status_line(self) -> str:
        """Clinical one-line summary."""
        if not self.findings:
            return "No issues detected."
        counts = self.finding_counts
        parts = []
        for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
            n = counts[sev]
            if n:
                parts.append(f"{n} {sev.value}")
        return ", ".join(parts)

    def model_dump_json_pretty(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)
