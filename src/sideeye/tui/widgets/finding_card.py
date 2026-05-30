"""FindingCard — single-finding display.

Two-line layout: severity glyph + category on the left header row, message
below, with optional excerpt and suggestion. Sized to its content (height: auto)
so multiple cards stack cleanly in a scrollable container.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from sideeye.models import Finding


class FindingCard(Vertical):
    """A single finding rendered as a compact card."""

    DEFAULT_CLASSES = "finding-card"

    def __init__(self, finding: Finding, **kwargs) -> None:
        super().__init__(**kwargs)
        self._finding = finding
        self.add_class(f"sev-{finding.level.value}")

    def compose(self) -> ComposeResult:
        f = self._finding

        header = Text()
        header.append(f.level.glyph, style=f"bold {f.level.color}")
        header.append("  ")
        header.append(f.level.value.upper(), style=f"bold {f.level.color}")
        header.append("   ")
        header.append(f.short_category, style="bold")
        # Multi-excerpt grouping: if finding has _extra_excerpts attached
        # (set by app when collapsing dupes), show count
        extras = getattr(f, "_extra_excerpts", None)
        if extras:
            header.append(f"   ({1 + len(extras)} matches)", style="dim")
        yield Static(header, classes="finding-header")

        yield Static(f.message, classes="finding-message")

        if f.excerpt:
            excerpt = f.excerpt if len(f.excerpt) < 140 else f.excerpt[:137] + "…"
            yield Static(Text(f"“{excerpt}”", style="dim italic"), classes="finding-excerpt")
            # Additional excerpts from collapsed dupes
            if extras:
                for ex in extras[:4]:
                    ex_short = ex if len(ex) < 140 else ex[:137] + "…"
                    yield Static(
                        Text(f"“{ex_short}”", style="dim italic"),
                        classes="finding-excerpt",
                    )

        if f.suggestion:
            yield Static(
                Text(f"→ {f.suggestion}", style="italic"),
                classes="finding-suggestion",
            )
