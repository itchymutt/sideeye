"""Tests for the user templates module."""

from __future__ import annotations

from pathlib import Path

import pytest

from sideeye.user_templates import (
    load_user_templates,
    pack_templates_dir,
    save_user_template,
    slugify,
    template_exists,
    templates_root,
)


@pytest.fixture
def isolated_templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point user templates at a temp directory."""
    monkeypatch.setenv("SIDEEYE_TEMPLATES_DIR", str(tmp_path))
    return tmp_path


# --------------------------------------------------------------------------- #
# Slugify
# --------------------------------------------------------------------------- #

def test_slugify_simple() -> None:
    assert slugify("My Daily Critique") == "my-daily-critique"


def test_slugify_handles_punctuation() -> None:
    assert slugify("Hello, World!!") == "hello-world"


def test_slugify_handles_unicode_and_strips_path() -> None:
    assert slugify("../../../etc/passwd") == "etc-passwd"


def test_slugify_collapses_repeated_separators() -> None:
    assert slugify("hello___world   foo") == "hello-world-foo"


def test_slugify_empty_falls_back_to_untitled() -> None:
    assert slugify("") == "untitled"
    assert slugify("!!!") == "untitled"


# --------------------------------------------------------------------------- #
# Save + load roundtrip
# --------------------------------------------------------------------------- #

def test_save_creates_file_with_frontmatter(isolated_templates: Path) -> None:
    result = save_user_template(
        pack_name="prompt-safety",
        title="My Critique",
        body="You are a senior product designer. Critique this.",
    )
    assert result.path.exists()
    assert result.path.name == "my-critique.md"
    assert result.overwrote is False

    content = result.path.read_text()
    assert content.startswith("---\n")
    assert "title: My Critique" in content
    assert "You are a senior product designer" in content


def test_save_writes_category_only_when_non_default(isolated_templates: Path) -> None:
    """The default category is 'personal'. Don't bloat the frontmatter when it's
    the default."""
    result = save_user_template(
        pack_name="prompt-safety",
        title="A",
        body="body text",
        category="personal",
    )
    content = result.path.read_text()
    assert "category:" not in content

    result = save_user_template(
        pack_name="prompt-safety",
        title="B",
        body="body text",
        category="critique",
    )
    content = result.path.read_text()
    assert "category: critique" in content


def test_save_refuses_to_overwrite_by_default(isolated_templates: Path) -> None:
    save_user_template("prompt-safety", "Same", "first body")
    with pytest.raises(FileExistsError):
        save_user_template("prompt-safety", "Same", "second body")


def test_save_overwrites_when_allowed(isolated_templates: Path) -> None:
    save_user_template("prompt-safety", "Same", "first body")
    result = save_user_template("prompt-safety", "Same", "second body", overwrite=True)
    assert result.overwrote is True
    content = result.path.read_text()
    assert "second body" in content
    assert "first body" not in content


def test_save_rejects_empty_title(isolated_templates: Path) -> None:
    with pytest.raises(ValueError):
        save_user_template("prompt-safety", "", "body")


def test_save_rejects_empty_body(isolated_templates: Path) -> None:
    with pytest.raises(ValueError):
        save_user_template("prompt-safety", "Title", "   ")


def test_load_returns_template_with_metadata(isolated_templates: Path) -> None:
    save_user_template(
        pack_name="prompt-safety",
        title="With Category",
        body="real body",
        category="critique",
        description="my notes",
    )
    templates = load_user_templates("prompt-safety")
    assert len(templates) == 1
    t = templates[0]
    assert t.title == "With Category"
    assert t.category == "critique"
    assert t.description == "my notes"
    assert t.body == "real body"


def test_load_empty_dir_returns_empty_list(isolated_templates: Path) -> None:
    assert load_user_templates("prompt-safety") == []


def test_load_sorts_by_mtime_desc(isolated_templates: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Most recently edited first."""
    import time
    save_user_template("prompt-safety", "First", "a")
    time.sleep(0.05)
    save_user_template("prompt-safety", "Second", "b")
    time.sleep(0.05)
    save_user_template("prompt-safety", "Third", "c")

    templates = load_user_templates("prompt-safety")
    titles = [t.title for t in templates]
    assert titles == ["Third", "Second", "First"]


def test_load_handles_no_frontmatter(isolated_templates: Path) -> None:
    """A markdown file without frontmatter still loads; title comes from first H1."""
    pack_dir = pack_templates_dir("prompt-safety")
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "raw.md").write_text("# Free Form Title\n\nThe body of the template.\n")

    templates = load_user_templates("prompt-safety")
    assert len(templates) == 1
    assert templates[0].title == "Free Form Title"
    assert templates[0].category == "personal"
    assert "The body of the template." in templates[0].body


def test_load_falls_back_to_filename(isolated_templates: Path) -> None:
    """No frontmatter, no H1 — title derives from filename."""
    pack_dir = pack_templates_dir("prompt-safety")
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "untitled-thing.md").write_text("Just body text, no headers.")

    templates = load_user_templates("prompt-safety")
    assert len(templates) == 1
    assert templates[0].title == "Untitled Thing"


def test_template_exists(isolated_templates: Path) -> None:
    assert template_exists("prompt-safety", "Anything") is False
    save_user_template("prompt-safety", "Real Template", "body")
    assert template_exists("prompt-safety", "Real Template") is True
    assert template_exists("prompt-safety", "real-template") is True  # slugifies same way
    assert template_exists("prompt-safety", "Different") is False


def test_pack_isolation(isolated_templates: Path) -> None:
    """Templates saved for one pack don't show up for another."""
    save_user_template("prompt-safety", "Only Prompt", "body")
    save_user_template("markdown", "Only Markdown", "body")
    prompt_t = load_user_templates("prompt-safety")
    md_t = load_user_templates("markdown")
    assert len(prompt_t) == 1
    assert len(md_t) == 1
    assert prompt_t[0].title == "Only Prompt"
    assert md_t[0].title == "Only Markdown"


# --------------------------------------------------------------------------- #
# Templates root resolution
# --------------------------------------------------------------------------- #

def test_templates_root_respects_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SIDEEYE_TEMPLATES_DIR", str(tmp_path / "explicit"))
    assert templates_root() == tmp_path / "explicit"


def test_templates_root_respects_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SIDEEYE_TEMPLATES_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert templates_root() == tmp_path / "sideeye" / "templates"
