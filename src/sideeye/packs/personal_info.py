"""Personal-info pack.

A user-configured pack for catching strings you specifically don't want to
leak in prompts: your name, family names, addresses, internal project
codenames, client names under NDA, etc.

The pack reads its rules from a TOML config file. By default that file lives
at `$XDG_CONFIG_HOME/sideeye/personal.toml` (typically `~/.config/sideeye/personal.toml`).

Example config:

    [strings]
    # Plain substrings — matched case-insensitively as whole-word where possible.
    names    = ["Jane Doe", "Pat Example"]
    emails   = ["test@personal.example"]
    phones   = ["555-0100"]
    addresses = ["123 Main St"]
    clients  = ["Acme Corp", "Globex"]

    [regex]
    # Each value is a regex (Python syntax). Use this for codenames with
    # variations, or anything more complex than a literal string.
    project_codenames = ["Project [A-Z][a-z]+", "Operation \\w+"]

The keys under `[strings]` and `[regex]` are arbitrary — they become the
category labels in findings. Pick names that read well in the UI.
"""

from __future__ import annotations

import difflib
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found]

from sideeye.models import Category, ScanResult, Severity
from sideeye.packs.base import BasePack, PackRule, RewriteResult

# --------------------------------------------------------------------------- #
# Config discovery
# --------------------------------------------------------------------------- #

def _default_config_path() -> Path:
    """Where the personal.toml config lives.

    Respects $XDG_CONFIG_HOME, falls back to ~/.config/sideeye/personal.toml.
    Also honors $SIDEEYE_PERSONAL_CONFIG for explicit override (useful for tests
    and for users who want to keep this file outside their home directory).
    """
    override = os.environ.get("SIDEEYE_PERSONAL_CONFIG")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "sideeye" / "personal.toml"


def _load_config(path: Path) -> dict | None:
    """Load the TOML config. Returns None if the file doesn't exist."""
    if not path.exists():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _build_rules_from_config(config: dict) -> list[PackRule]:
    """Translate the TOML structure into PackRule instances."""
    rules: list[PackRule] = []

    # [strings] — literal substrings, case-insensitive whole-word where the
    # input is alphanumeric.
    strings_section = config.get("strings", {})
    if isinstance(strings_section, dict):
        for category_key, values in strings_section.items():
            if not isinstance(values, list):
                continue
            for raw in values:
                if not isinstance(raw, str) or not raw.strip():
                    continue
                rules.append(_string_rule(category_key, raw))

    # [regex] — already-compiled patterns.
    regex_section = config.get("regex", {})
    if isinstance(regex_section, dict):
        for category_key, values in regex_section.items():
            if not isinstance(values, list):
                continue
            for raw in values:
                if not isinstance(raw, str) or not raw.strip():
                    continue
                try:
                    compiled = re.compile(raw, re.IGNORECASE)
                except re.error:
                    continue  # skip bad regex silently; user-error not crash
                rules.append(_regex_rule(category_key, raw, compiled))

    return rules


def _string_rule(category: str, literal: str) -> PackRule:
    """Build a rule for a literal substring match."""
    # If the literal is alphanumeric on both ends, anchor with word boundaries.
    # Otherwise (e.g. "test@example.com") use a plain case-insensitive match.
    needs_word_boundary = literal[0].isalnum() and literal[-1].isalnum()
    if needs_word_boundary:
        pattern = re.compile(rf"\b{re.escape(literal)}\b", re.IGNORECASE)
    else:
        pattern = re.compile(re.escape(literal), re.IGNORECASE)

    # Stable rule id based on category + first 16 chars of the literal.
    # Multiple literals in the same category get distinct ids.
    safe_literal = re.sub(r"\W+", "_", literal.lower())[:32]
    rule_id = f"personal_{category}_{safe_literal}"

    return PackRule(
        id=rule_id,
        category=category,
        severity=Severity.HIGH,
        message=f"Personal {category.replace('_', ' ')} detected in prompt.",
        suggestion=(
            "Redact or replace before sharing externally. If this is intentional, "
            "you can remove the entry from ~/.config/sideeye/personal.toml."
        ),
        pattern=pattern,
        confidence=0.99,
    )


def _regex_rule(category: str, raw: str, compiled: re.Pattern[str]) -> PackRule:
    safe_raw = re.sub(r"\W+", "_", raw.lower())[:32]
    rule_id = f"personal_{category}_re_{safe_raw}"
    return PackRule(
        id=rule_id,
        category=category,
        severity=Severity.HIGH,
        message=f"Personal {category.replace('_', ' ')} pattern detected.",
        suggestion="Redact or replace before sharing externally.",
        pattern=compiled,
        confidence=0.95,
    )


def _categories_from_config(config: dict) -> list[Category]:
    """Build a Category object for each section key actually used in the config."""
    seen: dict[str, Category] = {}
    for section in ("strings", "regex"):
        sec = config.get(section, {})
        if isinstance(sec, dict):
            for key in sec.keys():
                if key not in seen and isinstance(key, str):
                    seen[key] = Category(
                        id=key,
                        label=key.replace("_", " ").title(),
                        description=f"Personal {key.replace('_', ' ')}",
                    )
    return list(seen.values())


# --------------------------------------------------------------------------- #
# Empty-state guidance (shown when no config exists)
# --------------------------------------------------------------------------- #

_EMPTY_STATE_RULE = PackRule(
    id="personal_info_not_configured",
    category="setup",
    severity=Severity.LOW,
    message=(
        "Personal-info pack has no configuration. Create "
        "~/.config/sideeye/personal.toml with strings to watch for."
    ),
    suggestion=(
        "See `sideeye packs` or src/sideeye/packs/personal_info.py for an "
        "example config. Add your name, internal codenames, client names, etc."
    ),
    # This rule fires on every non-empty input so the user gets immediate feedback.
    detector=lambda t: [(0, min(len(t), 1), "(no config)")] if t.strip() else [],
    confidence=1.0,
)


# --------------------------------------------------------------------------- #
# The pack
# --------------------------------------------------------------------------- #

@dataclass
class PersonalInfoPack(BasePack):
    """User-configured personal-info linter.

    Rules come from a TOML file at $XDG_CONFIG_HOME/sideeye/personal.toml.
    The pack reloads its rules on construction, so editing the config and
    relaunching sideeye picks up changes.

    Set $SIDEEYE_PERSONAL_CONFIG to point at a custom config file.
    """

    name: str = "personal-info"
    label: str = "Personal Info"
    description: str = (
        "User-configured strings to watch for "
        "(your name, project codenames, NDA clients, etc.)."
    )
    file_extensions: tuple[str, ...] = ()
    categories: list[Category] = field(default_factory=list)
    rules: list[PackRule] = field(default_factory=list)
    templates: list = field(default_factory=list)

    # Path to the loaded config, for diagnostics. None when no config exists.
    config_path: Path | None = field(default=None)
    configured: bool = field(default=False)

    def __post_init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        """Re-read the config from disk. Useful after the user edits it."""
        path = _default_config_path()
        config = _load_config(path)

        if config is None:
            # No config: ship the empty-state hint as the only rule.
            self.configured = False
            self.config_path = None
            self.categories = [
                Category(id="setup", label="Setup", description="Pack configuration"),
            ]
            self.rules = [_EMPTY_STATE_RULE]
            return

        self.configured = True
        self.config_path = path
        self.categories = _categories_from_config(config)
        self.rules = _build_rules_from_config(config)

        # If config exists but is empty (e.g., user created the file but added
        # nothing), fall back to the empty-state rule.
        if not self.rules:
            self.rules = [_EMPTY_STATE_RULE]
            self.categories.append(
                Category(id="setup", label="Setup", description="Pack configuration"),
            )

    def detects(self, text: str) -> bool:
        # Never auto-activate. Personal-info is opt-in only — you have to
        # explicitly choose this pack with --pack personal-info.
        return False

    def should_use_optional_rules(self, text: str) -> bool:
        return False

    def rewrite(self, result: ScanResult) -> RewriteResult | None:
        """Redact every configured-sensitive string in the input.

        Each matched span is replaced with [REDACTED:category] so the user
        can see what was scrubbed and why. The category name comes from the
        TOML section the entry was in (names, emails, clients, etc.).

        When the only "finding" is the not-configured hint, do nothing —
        there's no real redaction work to do.
        """
        if not self.configured:
            return None  # honest empty state — pack isn't set up

        original = result.original_prompt
        findings = [f for f in result.findings if f.id != "personal_info_not_configured"]

        if not findings:
            # No real findings to redact — but the user pressed strip.
            # Return original unchanged with a note.
            return RewriteResult(
                original=original,
                rewritten=original,
                diff_lines=[],
                notes=["No configured sensitive strings detected in this prompt."],
            )

        # Replace each finding's span with [REDACTED:category]. Walk in reverse
        # span order so earlier offsets don't shift while we mutate.
        spans = sorted(
            (f for f in findings if f.span is not None),
            key=lambda f: f.span[0],
            reverse=True,
        )

        text = original
        notes: list[str] = []
        for f in spans:
            start, end = f.span  # type: ignore[misc]
            matched = text[start:end]
            placeholder = f"[REDACTED:{f.category}]"
            text = text[:start] + placeholder + text[end:]
            # Note format: matched substring → placeholder
            display_match = matched if len(matched) <= 60 else matched[:57] + "…"
            notes.append(f"redacted: “{display_match}” → {placeholder}")

        # Notes were collected in reverse order; flip back to original order.
        notes.reverse()

        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile="original",
                tofile="redacted",
                n=2,
            )
        )

        return RewriteResult(
            original=original,
            rewritten=text,
            diff_lines=diff_lines,
            notes=notes,
        )
