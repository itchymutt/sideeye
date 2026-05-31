"""Tests for third-party pack discovery via entry points."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch

from sideeye.models import Category, Severity
from sideeye.packs import get_pack, list_packs
from sideeye.packs.base import BasePack, PackRule
from sideeye.packs.registry import reload_third_party_packs


@dataclass
class _FakePack(BasePack):
    """Trivial third-party-style pack for testing discovery."""

    name: str = "fake-test"
    label: str = "Fake Test"
    description: str = "Test-only pack."
    file_extensions: tuple[str, ...] = (".fake",)
    categories: list[Category] = field(default_factory=lambda: [Category(id="test", label="Test")])

    def __post_init__(self) -> None:
        self.rules = [
            PackRule(
                id="fake-rule",
                category="test",
                severity=Severity.LOW,
                message="fake rule fired",
                detector=lambda text: [(0, 4, "fake")] if "fake" in text else [],
            ),
        ]


class _FakeEntryPoint:
    """Mimics importlib.metadata.EntryPoint for tests."""

    def __init__(self, name: str, value: str, pack_class: type) -> None:
        self.name = name
        self.value = value
        self._pack_class = pack_class

    def load(self) -> type:
        return self._pack_class


def test_third_party_pack_discovered():
    """A pack registered under sideeye.packs entry point is loadable via get_pack."""
    fake_ep = _FakeEntryPoint("fake-test", "tests.test_pack_discovery:_FakePack", _FakePack)

    def fake_entry_points(group: str):
        assert group == "sideeye.packs"
        return [fake_ep]

    with patch("sideeye.packs.registry.entry_points", fake_entry_points, create=True):
        reload_third_party_packs()
        pack = get_pack("fake-test")
        assert pack.name == "fake-test"
        assert isinstance(pack, _FakePack)

    reload_third_party_packs()  # cleanup


def test_third_party_pack_in_list_packs():
    """Discovered packs appear in list_packs()."""
    fake_ep = _FakeEntryPoint("fake-test", "x:_FakePack", _FakePack)

    def fake_entry_points(group: str):
        return [fake_ep]

    with patch("sideeye.packs.registry.entry_points", fake_entry_points, create=True):
        reload_third_party_packs()
        names = [p.name for p in list_packs()]
        assert "fake-test" in names
        # Builtins still there
        assert "prompt-safety" in names
        assert "markdown" in names

    reload_third_party_packs()


def test_builtin_wins_name_conflict():
    """A third-party pack with the same name as a builtin is shadowed."""
    # Try to register a pack named 'markdown' — builtin should still win
    fake_ep = _FakeEntryPoint("markdown", "x:_FakePack", _FakePack)

    def fake_entry_points(group: str):
        return [fake_ep]

    with patch("sideeye.packs.registry.entry_points", fake_entry_points, create=True):
        reload_third_party_packs()
        from sideeye.packs.markdown import MarkdownPack
        pack = get_pack("markdown")
        assert isinstance(pack, MarkdownPack), "builtin should not be shadowed"

    reload_third_party_packs()


def test_broken_pack_does_not_break_others():
    """If one third-party pack fails to load, others still work."""
    class _BrokenEntryPoint:
        name = "broken"
        value = "nonexistent.module:Nothing"

        def load(self):
            raise ImportError("simulated failure")

    fake_ep = _FakeEntryPoint("fake-test", "x:_FakePack", _FakePack)

    def fake_entry_points(group: str):
        return [_BrokenEntryPoint(), fake_ep]

    with patch("sideeye.packs.registry.entry_points", fake_entry_points, create=True):
        reload_third_party_packs()
        # Good one still loads
        assert get_pack("fake-test").name == "fake-test"
        # Broken one is absent (no KeyError raised when not asked for)
        names = [p.name for p in list_packs()]
        assert "broken" not in names

    reload_third_party_packs()


def test_non_protocol_pack_rejected():
    """A class that doesn't implement the Pack protocol is rejected."""
    class _NotAPack:
        pass

    fake_ep = _FakeEntryPoint("imposter", "x:_NotAPack", _NotAPack)

    def fake_entry_points(group: str):
        return [fake_ep]

    with patch("sideeye.packs.registry.entry_points", fake_entry_points, create=True):
        reload_third_party_packs()
        names = [p.name for p in list_packs()]
        assert "imposter" not in names

    reload_third_party_packs()


def test_no_entry_points_does_not_crash():
    """Sideeye with no third-party packs works fine."""
    def empty_entry_points(group: str):
        return []

    with patch("sideeye.packs.registry.entry_points", empty_entry_points, create=True):
        reload_third_party_packs()
        # Builtins still work
        assert get_pack("prompt-safety").name == "prompt-safety"
        assert len(list_packs()) >= 3

    reload_third_party_packs()


def test_base_pack_has_optional_file_path():
    """BasePack accepts an optional file_path attribute, default None."""
    from pathlib import Path
    pack = _FakePack()
    assert pack.file_path is None
    pack.file_path = Path("/tmp/test.fake")
    assert pack.file_path == Path("/tmp/test.fake")
