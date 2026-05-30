"""Tests for the personal-info pack — user-configured sensitive strings."""

from __future__ import annotations

from pathlib import Path

import pytest

from sideeye.models import Severity
from sideeye.packs.base import scan
from sideeye.packs.personal_info import PersonalInfoPack

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the pack at a temp config file. Returns the path."""
    config_path = tmp_path / "personal.toml"
    monkeypatch.setenv("SIDEEYE_PERSONAL_CONFIG", str(config_path))
    return config_path


def _write_config(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Empty-state behavior
# --------------------------------------------------------------------------- #

def test_pack_with_no_config_shows_setup_hint(
    isolated_config: Path,
) -> None:
    # Don't write the config file
    pack = PersonalInfoPack()
    assert pack.configured is False
    assert pack.config_path is None

    r = scan("any non-empty text", pack)
    assert len(r.findings) == 1
    assert r.findings[0].id == "personal_info_not_configured"


def test_pack_with_no_config_silent_on_empty_input(
    isolated_config: Path,
) -> None:
    pack = PersonalInfoPack()
    r = scan("", pack)
    assert len(r.findings) == 0


def test_pack_with_empty_config_falls_back_to_setup_hint(
    isolated_config: Path,
) -> None:
    _write_config(isolated_config, "")  # technically valid TOML
    pack = PersonalInfoPack()
    assert pack.configured is True  # the file exists, just empty
    r = scan("any text", pack)
    assert any(f.id == "personal_info_not_configured" for f in r.findings)


# --------------------------------------------------------------------------- #
# String rules
# --------------------------------------------------------------------------- #

def test_simple_name_match(isolated_config: Path) -> None:
    _write_config(isolated_config, """
[strings]
names = ["Jane Doe"]
""")
    pack = PersonalInfoPack()
    assert pack.configured
    r = scan("Hello Jane Doe, please review this.", pack)
    ids = [f.id for f in r.findings]
    assert len(r.findings) == 1
    assert ids[0].startswith("personal_names_")
    assert r.findings[0].severity == Severity.HIGH


def test_case_insensitive_match(isolated_config: Path) -> None:
    _write_config(isolated_config, """
[strings]
names = ["Jane Doe"]
""")
    pack = PersonalInfoPack()
    r = scan("hey JANE DOE", pack)
    assert len(r.findings) == 1


def test_word_boundary_for_alphanumeric_strings(isolated_config: Path) -> None:
    """A name should match as a whole word, not as a substring of another word."""
    _write_config(isolated_config, """
[strings]
names = ["Sam"]
""")
    pack = PersonalInfoPack()
    # "Samuel" should NOT match because "Sam" is a prefix, not a whole word
    r = scan("Samuel is reviewing this", pack)
    assert len(r.findings) == 0
    # But "Sam" should match
    r = scan("Sam is reviewing this", pack)
    assert len(r.findings) == 1


def test_email_substring_match(isolated_config: Path) -> None:
    """Emails contain special chars (@, .) so they shouldn't use word boundaries."""
    _write_config(isolated_config, """
[strings]
emails = ["test@example.com"]
""")
    pack = PersonalInfoPack()
    r = scan("Contact: test@example.com please.", pack)
    assert len(r.findings) == 1


def test_multiple_categories(isolated_config: Path) -> None:
    _write_config(isolated_config, """
[strings]
names = ["Jane Doe"]
clients = ["Acme Corp"]
emails = ["test@personal.com"]
""")
    pack = PersonalInfoPack()
    r = scan(
        "Jane Doe works for Acme Corp; reach him at test@personal.com",
        pack,
    )
    categories = {f.category for f in r.findings}
    assert categories == {"names", "clients", "emails"}


def test_multiple_values_in_one_category(isolated_config: Path) -> None:
    _write_config(isolated_config, """
[strings]
names = ["Jane Doe", "Pat Example", "Jane Doe"]
""")
    pack = PersonalInfoPack()
    r = scan("Jane Doe and Pat Example reviewed Jane Doe's work.", pack)
    assert len(r.findings) == 3
    excerpts = {f.excerpt for f in r.findings}
    assert excerpts == {"Jane Doe", "Pat Example"}


# --------------------------------------------------------------------------- #
# Regex rules
# --------------------------------------------------------------------------- #

def test_regex_match(isolated_config: Path) -> None:
    _write_config(isolated_config, """
[regex]
codenames = ["Project [A-Z][a-z]+"]
""")
    pack = PersonalInfoPack()
    r = scan("We discussed Project Sparrow in the meeting.", pack)
    assert len(r.findings) == 1
    assert r.findings[0].category == "codenames"


def test_invalid_regex_silently_skipped(isolated_config: Path) -> None:
    """A bad regex shouldn't crash the pack."""
    _write_config(isolated_config, """
[strings]
names = ["Jane Doe"]

[regex]
broken = ["[unclosed"]
good   = ["FOO-\\\\d+"]
""")
    pack = PersonalInfoPack()
    # Name rule still loaded
    r = scan("Jane Doe", pack)
    assert any(f.category == "names" for f in r.findings)
    # Good regex still loaded
    r = scan("FOO-123", pack)
    assert any(f.category == "good" for f in r.findings)
    # Broken regex was skipped, not crashed


# --------------------------------------------------------------------------- #
# Reload behavior
# --------------------------------------------------------------------------- #

def test_reload_picks_up_config_changes(isolated_config: Path) -> None:
    _write_config(isolated_config, """
[strings]
names = ["Sam"]
""")
    pack = PersonalInfoPack()
    r = scan("Sam", pack)
    assert len(r.findings) == 1

    # Add a new entry
    _write_config(isolated_config, """
[strings]
names = ["Sam", "Pat"]
""")
    pack.reload()
    r = scan("Sam and Pat", pack)
    assert len(r.findings) == 2


def test_pack_does_not_auto_detect(isolated_config: Path) -> None:
    """Personal-info should never auto-activate. Opt-in only."""
    _write_config(isolated_config, """
[strings]
names = ["Sam"]
""")
    pack = PersonalInfoPack()
    # Even text full of personal info shouldn't trigger detection
    assert pack.detects("Sam was here") is False


def test_unconfigured_pack_returns_none_from_rewrite(isolated_config: Path) -> None:
    """When the pack has no config, rewrite is meaningless — return None so the
    TUI shows the appropriate "set me up" message."""
    pack = PersonalInfoPack()
    assert pack.configured is False
    from sideeye.models import ScanResult
    result = ScanResult(original_prompt="Sam", pack="personal-info")
    assert pack.rewrite(result) is None


def test_redacts_each_finding_with_category_placeholder(isolated_config: Path) -> None:
    """Configured strings get replaced with [REDACTED:category] markers."""
    _write_config(isolated_config, """
[strings]
names = ["Jane Doe"]
emails = ["test@example.com"]
""")
    pack = PersonalInfoPack()
    result = scan("Hi, I'm Jane Doe. Reply to test@example.com please.", pack)

    rewrite = pack.rewrite(result)
    assert rewrite is not None
    assert "[REDACTED:names]" in rewrite.rewritten
    assert "[REDACTED:emails]" in rewrite.rewritten
    assert "Jane Doe" not in rewrite.rewritten
    assert "test@example.com" not in rewrite.rewritten
    # Surrounding context preserved
    assert "Hi, I'm" in rewrite.rewritten
    assert "Reply to" in rewrite.rewritten


def test_redaction_handles_multiple_matches_same_category(isolated_config: Path) -> None:
    """Multiple strings in the same category each get redacted."""
    _write_config(isolated_config, """
[strings]
names = ["Sam", "Pat"]
""")
    pack = PersonalInfoPack()
    result = scan("Sam met with Pat today.", pack)
    rewrite = pack.rewrite(result)
    assert rewrite is not None
    assert rewrite.rewritten.count("[REDACTED:names]") == 2


def test_redaction_notes_quote_actual_substrings(isolated_config: Path) -> None:
    """The notes should quote the exact original text, not generic labels."""
    _write_config(isolated_config, """
[strings]
names = ["Jane Doe"]
""")
    pack = PersonalInfoPack()
    result = scan("Hello Jane Doe.", pack)
    rewrite = pack.rewrite(result)
    assert rewrite is not None
    assert any("Jane Doe" in n for n in rewrite.notes)
    assert any("[REDACTED:names]" in n for n in rewrite.notes)


def test_redaction_skips_setup_hint_finding(isolated_config: Path) -> None:
    """When the pack isn't configured but rewrite is somehow called with the
    setup-hint finding, we don't redact anything."""
    # Don't write a config — pack is unconfigured
    pack = PersonalInfoPack()
    assert pack.configured is False
    from sideeye.models import ScanResult
    result = ScanResult(original_prompt="hello", pack="personal-info")
    rewrite = pack.rewrite(result)
    # Unconfigured pack returns None (per the earlier test)
    assert rewrite is None


def test_redaction_with_no_real_findings(isolated_config: Path) -> None:
    """Configured pack, but the prompt has nothing to redact."""
    _write_config(isolated_config, """
[strings]
names = ["Sam"]
""")
    pack = PersonalInfoPack()
    result = scan("Nothing sensitive here at all.", pack)
    rewrite = pack.rewrite(result)
    assert rewrite is not None
    assert rewrite.rewritten == result.original_prompt
    assert "No configured sensitive strings" in rewrite.notes[0]
