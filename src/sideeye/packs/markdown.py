"""Markdown lint pack.

Catches common markdown problems: trailing whitespace, missing alt text,
mixed heading levels, bare URLs, TODO comments, banned-word lists.

Demonstrates that the SideEye engine is genuinely domain-neutral.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sideeye.models import Category, Severity
from sideeye.packs.base import BasePack, PackRule, Template

# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #

CATEGORIES: list[Category] = [
    Category(id="formatting", label="Formatting"),
    Category(id="accessibility", label="Accessibility"),
    Category(id="hygiene", label="Hygiene"),
    Category(id="style", label="Style"),
    Category(id="links", label="Links"),
]


# --------------------------------------------------------------------------- #
# Detectors
# --------------------------------------------------------------------------- #

def _detect_trailing_whitespace(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    pos = 0
    for line in text.split("\n"):
        if line and line != line.rstrip():
            # Find the trailing whitespace run
            stripped_len = len(line.rstrip())
            ws_start = pos + stripped_len
            ws_end = pos + len(line)
            spans.append((ws_start, ws_end, "  ← trailing whitespace"))
        pos += len(line) + 1  # +1 for the newline
    return spans[:10]  # cap to avoid spammy output


def _detect_missing_alt_text(text: str) -> list[tuple[int, int, str]]:
    # ![alt](url) — empty alt is a violation
    spans = []
    for m in re.finditer(r"!\[(\s*)\]\(([^)]+)\)", text):
        spans.append((m.start(), m.end(), m.group(0)))
    return spans


def _detect_bare_urls(text: str) -> list[tuple[int, int, str]]:
    # Bare URLs not wrapped in markdown link syntax or angle brackets
    spans = []
    for m in re.finditer(
        r"(?<![(\[<\"])https?://[^\s<>)\]]+",
        text,
    ):
        # Skip if it's inside backticks (code)
        start = m.start()
        before = text[:start]
        backticks_before = before.count("`") - before.count("``")
        if backticks_before % 2 == 1:
            continue
        spans.append((start, m.end(), m.group(0)))
    return spans[:8]


def _detect_heading_jump(text: str) -> list[tuple[int, int, str]]:
    """Flag heading-level jumps (e.g., # then ###, skipping ##)."""
    spans = []
    prev_level: int | None = None
    pos = 0
    for line in text.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            if prev_level is not None and level > prev_level + 1:
                start = pos
                end = pos + len(m.group(0))
                spans.append((start, end, m.group(0).strip()))
            prev_level = level
        pos += len(line) + 1
    return spans[:5]


def _detect_todo(text: str) -> list[tuple[int, int, str]]:
    spans = []
    for m in re.finditer(r"(?i)\b(TODO|FIXME|XXX|HACK)\b[: ]?[^.\n]{0,80}", text):
        spans.append((m.start(), m.end(), m.group(0)[:80]))
    return spans[:6]


def _detect_lazy_link_text(text: str) -> list[tuple[int, int, str]]:
    # [click here](...) or [here](...) or [link](...) — non-descriptive link text
    spans = []
    for m in re.finditer(
        r"\[(click here|here|link|this|read more|more)\]\([^)]+\)",
        text,
        re.IGNORECASE,
    ):
        spans.append((m.start(), m.end(), m.group(0)))
    return spans


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #

RULES: list[PackRule] = [
    PackRule(
        id="trailing_whitespace",
        category="hygiene",
        severity=Severity.LOW,
        message="Trailing whitespace on a line.",
        suggestion="Strip trailing whitespace. Most editors do this on save.",
        detector=_detect_trailing_whitespace,
        confidence=0.99,
    ),
    PackRule(
        id="missing_alt_text",
        category="accessibility",
        severity=Severity.HIGH,
        message="Image missing alt text. Screen readers can't describe this image.",
        suggestion="Add descriptive alt text inside the brackets: ![A red bicycle](...)",
        detector=_detect_missing_alt_text,
        confidence=0.95,
    ),
    PackRule(
        id="bare_url",
        category="links",
        severity=Severity.LOW,
        message="Bare URL in prose. Most renderers handle it, but link text is more readable.",
        suggestion="Use [descriptive text](url) instead of pasting the raw URL.",
        detector=_detect_bare_urls,
    ),
    PackRule(
        id="heading_jump",
        category="formatting",
        severity=Severity.MEDIUM,
        message="Heading level jumps (e.g., # → ###). Breaks document outline and a11y.",
        suggestion="Use sequential heading levels: # then ##, never skip.",
        detector=_detect_heading_jump,
        confidence=0.9,
    ),
    PackRule(
        id="todo_comment",
        category="hygiene",
        severity=Severity.MEDIUM,
        message="TODO/FIXME/HACK left in the document.",
        suggestion="Resolve or move to an issue tracker before publishing.",
        detector=_detect_todo,
    ),
    PackRule(
        id="lazy_link_text",
        category="accessibility",
        severity=Severity.MEDIUM,
        message="Non-descriptive link text ('click here', 'read more').",
        suggestion="Describe the destination: [installation guide] rather than [click here].",
        detector=_detect_lazy_link_text,
        confidence=0.95,
    ),
    PackRule(
        id="multiple_blank_lines",
        category="hygiene",
        severity=Severity.LOW,
        message="3+ consecutive blank lines.",
        suggestion="Collapse to at most one blank line between blocks.",
        pattern=re.compile(r"\n\n\n+"),
    ),
]


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #

TEMPLATES: list[Template] = [
    Template(
        id="readme-skeleton",
        title="README skeleton",
        category="docs",
        description="A clean, complete README starter.",
        body=(
            "# Project Name\n\n"
            "One-sentence description of what this does.\n\n"
            "## Install\n\n"
            "```bash\n"
            "pipx install project-name\n"
            "```\n\n"
            "## Use\n\n"
            "```bash\n"
            "project-name --help\n"
            "```\n\n"
            "## Develop\n\n"
            "```bash\n"
            "git clone ...\n"
            "pip install -e \".[dev]\"\n"
            "pytest\n"
            "```\n\n"
            "## License\n\n"
            "MIT.\n"
        ),
    ),
    Template(
        id="changelog-entry",
        title="Changelog entry",
        category="docs",
        description="Keep-a-changelog style entry.",
        body=(
            "## [Unreleased]\n\n"
            "### Added\n"
            "- \n\n"
            "### Changed\n"
            "- \n\n"
            "### Fixed\n"
            "- \n\n"
            "### Removed\n"
            "- \n"
        ),
    ),
    Template(
        id="blog-post",
        title="Blog post starter",
        category="writing",
        description="Lede, body, ending.",
        body=(
            "# Title\n\n"
            "_One-sentence summary of what the reader will learn._\n\n"
            "## The problem\n\n"
            "What hurts and why anyone should care.\n\n"
            "## The approach\n\n"
            "What you did. Be concrete.\n\n"
            "## What it cost\n\n"
            "The honest tradeoffs.\n\n"
            "## What's next\n\n"
            "The follow-up question or invitation.\n"
        ),
    ),
]


# --------------------------------------------------------------------------- #
# The pack
# --------------------------------------------------------------------------- #

@dataclass
class MarkdownPack(BasePack):
    name: str = "markdown"
    label: str = "Markdown"
    description: str = "Markdown style, accessibility, and hygiene checks."
    file_extensions: tuple[str, ...] = (".md", ".mdx", ".markdown")
    categories: list[Category] = field(default_factory=lambda: list(CATEGORIES))
    rules: list[PackRule] = field(default_factory=lambda: list(RULES))
    templates: list[Template] = field(default_factory=lambda: list(TEMPLATES))

    def detects(self, text: str) -> bool:
        """Heuristic: looks like markdown if there are markdown markers."""
        signals = ("\n# ", "\n## ", "\n- ", "\n* ", "](", "```")
        # Strong signal: starts with a heading or fence
        if text.startswith(("#", "```")):
            return True
        return sum(1 for s in signals if s in text) >= 2

    def should_use_optional_rules(self, text: str) -> bool:
        return False
