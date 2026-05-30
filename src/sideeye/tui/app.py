"""SideEye main Textual application.

A precise, local safety co-pilot for prompts and agent traces.
"""

from __future__ import annotations

import traceback
from pathlib import Path

import pyperclip
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.timer import Timer
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    TextArea,
)

from sideeye import __version__
from sideeye.models import RiskLevel, ScanResult
from sideeye.packs import DEFAULT_PACK, get_pack, pack_for_text
from sideeye.packs.base import Pack, Template, scan
from sideeye.remixer import safe_remix
from sideeye.scanner import scan_trace
from sideeye.tui.widgets.finding_card import FindingCard
from sideeye.user_templates import (
    load_user_templates,
    pack_templates_dir,
    save_user_template,
    slugify,
    template_exists,
)

# --------------------------------------------------------------------------- #
# Themes — two only. Standard for daily work, High Contrast for accessibility.
# --------------------------------------------------------------------------- #

STANDARD_THEME = Theme(
    name="standard",
    primary="#5B9BD5",
    secondary="#7BA3C9",
    accent="#4A9C7E",
    background="#0F1218",
    surface="#181C25",
    panel="#212630",
    error="#D46B6B",
    warning="#D4A84B",
    success="#4A9C7E",
)

HIGH_CONTRAST_THEME = Theme(
    name="high-contrast",
    primary="#A8C5E0",
    secondary="#C5D9E8",
    accent="#7FCFA8",
    background="#000000",
    surface="#0D1117",
    panel="#1A212B",
    error="#FF7B7B",
    warning="#FFD27A",
    success="#A8E0BD",
)


# --------------------------------------------------------------------------- #
# Template picker — single ListView, no preview pane.
# --------------------------------------------------------------------------- #

class TemplateItem(ListItem):
    """One row in the template list. user=True styles it for the 'Mine' section."""

    def __init__(self, template: Template, user: bool = False) -> None:
        super().__init__()
        self.template = template
        self.user = user

    def compose(self) -> ComposeResult:
        line = Text()
        if self.user:
            # Concrete color, not a Textual CSS variable — Rich.Text styles
            # are resolved by Rich, not Textual.
            line.append("● ", style="bold green")
        line.append(self.template.title, style="bold")
        line.append("   ")
        line.append(self.template.category.lower(), style="dim italic")
        yield Static(line, classes="template-line")


class TemplateHeader(ListItem):
    """Non-selectable section header inside the list."""

    def __init__(self, label: str) -> None:
        super().__init__()
        self.add_class("template-header")
        self._label = label

    def compose(self) -> ComposeResult:
        yield Static(f"[dim bold]── {self._label} ──[/]", markup=True)


class TemplatePicker(ModalScreen[Template | None]):
    """Two-section picker: user templates on top, built-in below."""

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Cancel"),
    ]

    CSS = """
    TemplatePicker {
        align: center middle;
    }

    #template-modal {
        width: 76;
        height: auto;
        max-height: 80%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }

    #template-modal Label {
        color: $text-muted;
        margin-bottom: 1;
    }

    #template-list {
        height: auto;
        max-height: 22;
        border: none;
        background: $surface;
    }

    #template-list > ListItem {
        padding: 0 1;
        background: $surface;
    }

    #template-list > ListItem.--highlight {
        background: $primary 20%;
    }

    #template-list > ListItem.template-header {
        background: $surface;
        padding: 0 1;
    }

    #template-list > ListItem.template-header.--highlight {
        background: $surface;
    }

    .template-line {
        padding: 0;
    }
    """

    def __init__(
        self,
        user_templates: list[Template],
        builtin_templates: list[Template] | None = None,
    ) -> None:
        super().__init__()
        self._user_templates = user_templates
        self._builtin_templates = builtin_templates or []
        # Flat selectable list (excludes headers) for number-key quickselect.
        self._all_templates: list[Template] = [*user_templates, *self._builtin_templates]

    def compose(self) -> ComposeResult:
        with Vertical(id="template-modal"):
            if not self._all_templates:
                yield Label(
                    "No templates for this pack yet.\n\n"
                    "ctrl+shift+s in the editor to save your current prompt."
                )
                return
            yield Label("Templates  ·  ↑↓ navigate  ·  enter select  ·  esc cancel")

            items: list[ListItem] = []
            if self._user_templates:
                items.append(TemplateHeader("Mine"))
                for tpl in self._user_templates:
                    items.append(TemplateItem(tpl, user=True))
            if self._builtin_templates:
                if self._user_templates:
                    items.append(TemplateHeader("Built-in"))
                for tpl in self._builtin_templates:
                    items.append(TemplateItem(tpl, user=False))

            yield ListView(*items, id="template-list")

    def on_mount(self) -> None:
        if not self._all_templates:
            return
        lv = self.query_one("#template-list", ListView)
        # Start on the first SELECTABLE item, not the header.
        for i, item in enumerate(lv.children):
            if isinstance(item, TemplateItem):
                lv.index = i
                break
        lv.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, TemplateItem):
            self.dismiss(event.item.template)
        # Selecting a header is a no-op; the user can keep navigating.

    def on_key(self, event) -> None:
        # Number quick-select picks from the flat list of selectable templates.
        if event.key in "123456789":
            idx = int(event.key) - 1
            if 0 <= idx < len(self._all_templates):
                event.stop()
                self.dismiss(self._all_templates[idx])


# --------------------------------------------------------------------------- #
# Help modal
# --------------------------------------------------------------------------- #

HELP_TEXT = f"""[bold]SideEye v{__version__}[/]

A local text linter with pluggable rule packs. No network, no model calls,
no telemetry. Rules are regex + Python in src/sideeye/packs/.

[bold $primary]Workflow[/]
  1. Type or paste text. Auto-scans 350ms after you stop typing.
  2. Review findings on the right, sorted by severity.
  3. ctrl+r strips risky phrases from your prompt in place.
  4. ctrl+z to undo if you don't like it.
  5. ctrl+y to copy the editor contents to your clipboard.

[bold $primary]Packs[/]
  prompt-safety   LLM prompt and agent-trace safety (default)
  markdown        Markdown style and accessibility
  personal-info   User-configured strings (your name, codenames, NDA clients)

  Active pack shown in the top bar. SideEye auto-detects from content
  unless you pass --pack at launch.

[bold $primary]What gets flagged[/]
  SideEye catches [bold]documented attack patterns[/], not arbitrary text. The
  prompt-safety rules fire on specific known phrases (DAN, "ignore all
  previous instructions", common API key formats, etc.), not on every name
  or capitalized word.

  For project-specific concerns (your real name, internal codenames, client
  names), use the personal-info pack with a config at
  [bold]~/.config/sideeye/personal.toml[/]. See examples/personal.toml.example
  in the repo. Then: [bold]sideeye --pack personal-info[/]

[bold $primary]What ctrl+r does (and doesn't do)[/]
  ctrl+r is a [bold]safety filter[/], not a creative coach. It removes
  documented-risk phrases (injection, jailbreak, named overrides, intensifier
  fluff) and tidies the gaps. It does NOT rewrite your prompt to be "better"
  or prepend a guardrail paragraph. That's your job — the finding suggestions
  on the right teach you how.

[bold $primary]Keys[/]
  ctrl+s        scan now
  ctrl+r        strip risky phrases from prompt — applies in place
  ctrl+shift+r  preview the strip side-by-side before applying
  ctrl+y        copy editor contents to clipboard
  ctrl+z        undo (built into the editor)
  ctrl+t        templates (pack-specific; yours first, then built-in)
  ctrl+shift+s  save current editor content as a user template
  ctrl+v        paste from clipboard
  ctrl+l        load from file
  ctrl+shift+t  toggle high-contrast theme
  esc           clear editor (or dismiss modal)
  f1            this help
  ctrl+q        quit

[bold $primary]Templates[/]
  Saved at ~/.config/sideeye/templates/<pack>/<slug>.md as plain markdown
  with optional YAML frontmatter (title, category, description). Edit them
  with any editor — sideeye reads them fresh every time the picker opens.

[bold $primary]Headless / CI[/]
  sideeye packs                       list available packs
  sideeye scan "your text"            pretty output, auto-detected pack
  sideeye scan -p markdown < FILE     specific pack, pipe input
  sideeye scan -p personal-info < f   check for your configured PII
  sideeye scan --json < file          machine-readable
  sideeye check -f README.md          CI gate: exit 1 if HIGH+ found

[dim]Press any key to close.[/]
"""


class HelpScreen(ModalScreen[None]):
    """Dismisses on any key."""

    CSS = """
    HelpScreen { align: center middle; }

    #help-modal {
        width: 76;
        height: auto;
        max-height: 90%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }

    #help-text {
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="help-modal"):
            yield Static(HELP_TEXT, id="help-text", markup=True)

    def on_key(self, event) -> None:
        # Stop propagation so escape doesn't bubble to the app-level clear binding.
        event.stop()
        self.dismiss(None)


# --------------------------------------------------------------------------- #
# Quick file load
# --------------------------------------------------------------------------- #

class QuickLoad(ModalScreen[Path | None]):
    CSS = """
    QuickLoad { align: center middle; }
    #quick-load-modal {
        width: 76;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    #quick-load-modal Input { width: 100%; margin: 1 0; }
    """

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="quick-load-modal"):
            yield Label("Load prompt from file")
            yield Input(placeholder="~/prompts/risky.txt", id="path-input")
            with Horizontal():
                yield Button("Load", variant="primary", id="load-btn")
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#path-input", Input).focus()

    @on(Input.Submitted, "#path-input")
    def _on_submit(self) -> None:
        self._try_load()

    @on(Button.Pressed, "#load-btn")
    def _on_load(self) -> None:
        self._try_load()

    @on(Button.Pressed, "#cancel-btn")
    def _on_cancel(self) -> None:
        self.dismiss(None)

    def _try_load(self) -> None:
        p = Path(self.query_one("#path-input", Input).value).expanduser()
        if p.exists() and p.is_file():
            self.dismiss(p)
        else:
            self.app.notify(f"File not found: {p}", severity="error")


# --------------------------------------------------------------------------- #
# Remix preview modal — side-by-side, deliberate-mode review
# --------------------------------------------------------------------------- #

class RemixPreview(ModalScreen[str | None]):
    """Side-by-side view of the original vs the proposed remix.

    Returns "apply" when accepted, None when cancelled. The caller is
    responsible for writing the remix back to the editor.
    """

    BINDINGS = [
        Binding("enter", "apply", "Apply", show=True, priority=True),
        Binding("escape", "dismiss(None)", "Cancel", show=True, priority=True),
        Binding("c", "copy_remix", "Copy remix", show=True),
    ]

    CSS = """
    RemixPreview { align: center middle; }

    #preview-modal {
        width: 90%;
        height: 90%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }

    #preview-head {
        height: 1;
        margin-bottom: 1;
    }

    #preview-split {
        height: 1fr;
    }

    .preview-col {
        width: 1fr;
        padding: 0 1;
    }

    .preview-col-label {
        height: 1;
        color: $text-muted;
        text-style: bold;
        margin-bottom: 1;
    }

    .preview-body {
        height: 1fr;
        border: round $panel;
        padding: 1;
        background: $background;
    }

    #preview-notes {
        height: auto;
        max-height: 10;
        margin-top: 1;
        padding: 1;
        background: $panel;
        color: $text-muted;
    }

    #preview-keys {
        height: 1;
        margin-top: 1;
        color: $text-muted;
        text-align: center;
    }
    """

    def __init__(
        self,
        original: str,
        rewritten: str,
        notes: list[str],
        before_severity: RiskLevel,
        before_count: int,
    ) -> None:
        super().__init__()
        self._original = original
        self._rewritten = rewritten
        self._notes = notes
        self._before_severity = before_severity
        self._before_count = before_count

    def compose(self) -> ComposeResult:
        with Vertical(id="preview-modal"):
            yield Static("", id="preview-head")

            with Horizontal(id="preview-split"):
                with Vertical(classes="preview-col"):
                    yield Static("ORIGINAL", classes="preview-col-label")
                    with VerticalScroll(classes="preview-body"):
                        yield Static(self._original)
                with Vertical(classes="preview-col"):
                    yield Static("AFTER STRIP", classes="preview-col-label")
                    with VerticalScroll(classes="preview-body"):
                        yield Static(self._rewritten)

            yield Static("", id="preview-notes")
            yield Static(
                "[bold]enter[/] apply  ·  [bold]c[/] copy remix  ·  [bold]esc[/] cancel",
                id="preview-keys",
                markup=True,
            )

    def on_mount(self) -> None:
        head = self.query_one("#preview-head", Static)
        h = Text()
        h.append("STRIP PREVIEW  ", style="bold")
        h.append(self._before_severity.value.upper(), style=f"bold {self._before_severity.color}")
        h.append(f"   {self._before_count} findings   ", style="dim")
        h.append(f"{len(self._notes)} change{'s' if len(self._notes) != 1 else ''} proposed", style="dim italic")
        head.update(h)

        notes_w = self.query_one("#preview-notes", Static)
        if self._notes:
            body = Text("CHANGES\n", style="bold")
            for n in self._notes:
                body.append(f"  · {n}\n")
            notes_w.update(body)
        else:
            notes_w.update(Text("No specific changes — only safety boilerplate added.", style="dim italic"))

    def action_apply(self) -> None:
        self.dismiss("apply")

    def action_copy_remix(self) -> None:
        try:
            pyperclip.copy(self._rewritten)
            self.app.notify("Remix copied to clipboard.", severity="information", timeout=2)
        except Exception as e:
            self.app.notify(f"Clipboard error: {e}", severity="error", timeout=3)


# --------------------------------------------------------------------------- #
# Save-template modals
# --------------------------------------------------------------------------- #

class TitlePrompt(ModalScreen[str | None]):
    """Single-line input asking the user to title a new template."""

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Cancel"),
    ]

    CSS = """
    TitlePrompt { align: center middle; }
    #title-modal {
        width: 64;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    #title-modal Label { color: $text-muted; margin-bottom: 1; }
    #title-modal Input { width: 100%; margin: 1 0; }
    """

    def __init__(self, prefill: str = "") -> None:
        super().__init__()
        self._prefill = prefill

    def compose(self) -> ComposeResult:
        with Vertical(id="title-modal"):
            yield Label("Save as template — enter a title")
            yield Input(
                value=self._prefill,
                placeholder="Daily critique starter",
                id="title-input",
            )
            yield Static(
                "[dim]enter to save · esc to cancel[/]",
                markup=True,
            )

    def on_mount(self) -> None:
        inp = self.query_one("#title-input", Input)
        inp.focus()
        if self._prefill:
            inp.action_end()  # cursor to end so the user can keep typing

    @on(Input.Submitted, "#title-input")
    def _on_submit(self) -> None:
        title = self.query_one("#title-input", Input).value.strip()
        if not title:
            self.app.notify("Title is required.", severity="warning", timeout=2)
            return
        self.dismiss(title)


class OverwriteConfirm(ModalScreen[bool]):
    """Yes/no dialog asking whether to overwrite an existing template file."""

    BINDINGS = [
        Binding("escape", "dismiss(False)", "Cancel"),
        Binding("y", "confirm", "Yes"),
        Binding("n", "dismiss(False)", "No"),
    ]

    CSS = """
    OverwriteConfirm { align: center middle; }
    #overwrite-modal {
        width: 64;
        height: auto;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }
    #overwrite-modal Label { color: $text; margin-bottom: 1; }
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        with Vertical(id="overwrite-modal"):
            yield Label(f"Template already exists at\n  {self._path}\n\nOverwrite?")
            yield Static("[dim]y to overwrite · n or esc to cancel[/]", markup=True)

    def action_confirm(self) -> None:
        self.dismiss(True)


# --------------------------------------------------------------------------- #
# Main App
# --------------------------------------------------------------------------- #

class SideEyeApp(App):
    """The SideEye TUI."""

    CSS_PATH = "styles.tcss"
    TITLE = "sideeye"
    # Disable Textual's built-in command palette; sideeye is keyboard-driven via
    # its own bindings. The footer was showing a stray "^p palette" entry.
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True, priority=True),
        Binding("ctrl+s", "scan", "Scan", show=True, priority=True),
        Binding("ctrl+r", "remix", "Strip Risks", show=True, priority=True),
        Binding("ctrl+shift+r", "preview_remix", "Preview Strip", show=False, priority=True),
        Binding("ctrl+y", "copy_editor", "Copy", show=True, priority=True),
        Binding("ctrl+t", "open_templates", "Templates", show=True, priority=True),
        Binding("ctrl+shift+s", "save_template", "Save Template", show=True, priority=True),
        Binding("ctrl+l", "load_file", "Load", show=True, priority=True),
        Binding("ctrl+shift+t", "toggle_theme", "Theme", show=False, priority=True),
        Binding("f1", "help", "Help", show=True, priority=True),
        # Escape is NOT priority. App-level priority bindings fire even when a
        # modal is active, which would leak escape past modal handlers and clear
        # the editor underneath the modal. Without priority, modals get first
        # crack at escape via their own BINDINGS / on_key.
        Binding("escape", "clear", "Clear", show=False),
        # ctrl+v handled by TextArea natively; we don't override.
    ]

    current_result: reactive[ScanResult | None] = reactive(None)

    def __init__(self, initial_pack: Pack | None = None) -> None:
        super().__init__()
        self._scan_timer: Timer | None = None
        # Pack-aware: the active pack determines rules, templates, and label.
        # If no pack is specified at launch, we use the default and let
        # auto-detection swap it on the first scan.
        self._pack: Pack = initial_pack or get_pack(DEFAULT_PACK)
        self._pack_locked: bool = initial_pack is not None
        self.register_theme(STANDARD_THEME)
        self.register_theme(HIGH_CONTRAST_THEME)
        self.theme = "standard"

    # ------------------------------------------------------------------ #
    # Compose
    # ------------------------------------------------------------------ #

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            yield Static("", id="top-bar")

            with Horizontal(id="main-split"):
                # LEFT: editor + last-remix history strip
                with Vertical(id="left-pane"):
                    yield Static("", id="pane-label", classes="pane-label")
                    yield TextArea.code_editor(
                        "",
                        id="prompt-editor",
                        language="markdown",
                        soft_wrap=True,
                        # tab_behavior="focus": "indent" makes TextArea eat
                        # escape (uses it for focus-next), blocking the app's
                        # escape→clear binding. "focus" is also the correct
                        # behavior for a prompt editor.
                        tab_behavior="focus",
                        show_line_numbers=False,
                    )
                    # Persistent strip showing the last remix's changes.
                    # Hidden until the first remix is applied.
                    with VerticalScroll(id="remix-history", classes="remix-history-hidden"):
                        yield Static("", id="remix-history-content")

                # RIGHT: status + findings
                with Vertical(id="right-pane"):
                    yield Static("", id="status-line", classes="status-line")
                    with VerticalScroll(id="findings-scroll"):
                        yield Static(
                            "Type or paste a prompt on the left. Scans run automatically.",
                            classes="empty-state",
                        )

        yield Footer()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def on_mount(self) -> None:
        self._refresh_top_bar()
        self._refresh_pane_label()
        self._refresh_status_line(None)
        editor = self.query_one("#prompt-editor", TextArea)
        editor.focus()

    def _refresh_pane_label(self) -> None:
        """Pack-aware label for the input pane."""
        label = self.query_one("#pane-label", Static)
        # prompt-safety → "PROMPT", markdown → "MARKDOWN", etc.
        text = self._pack.label.upper()
        label.update(text)

    def handle_exception(self, error: Exception) -> None:
        """Crash handler. Logs to file, notifies user, does not crash the loop."""
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        log_path = self._crash_log_path()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a") as f:
                f.write("\n=== SIDEEYE CRASH ===\n")
                f.write(tb)
                f.write("=====================\n")
        except OSError:
            pass
        self.notify(f"Error (logged to {log_path}): {error}", severity="error", timeout=10)

    @staticmethod
    def _crash_log_path() -> Path:
        import os
        base = os.environ.get("XDG_STATE_HOME")
        if base:
            return Path(base) / "sideeye" / "crash.log"
        return Path.home() / ".local" / "state" / "sideeye" / "crash.log"

    # ------------------------------------------------------------------ #
    # Top bar + status line
    # ------------------------------------------------------------------ #

    def _refresh_top_bar(self) -> None:
        bar = self.query_one("#top-bar", Static)
        line = Text("sideeye", style="bold")
        line.append(f"  v{__version__}", style="dim")
        line.append("    ")
        line.append(f"pack: {self._pack.name}", style="dim")
        if self._pack_locked:
            line.append("  (locked)", style="dim italic")
        bar.update(line)

    def _refresh_status_line(self, result: ScanResult | None) -> None:
        widget = self.query_one("#status-line", Static)
        widget.remove_class("sev-low", "sev-medium", "sev-high", "sev-critical")

        if result is None or not result.original_prompt.strip():
            widget.add_class("sev-none")
            widget.update(Text("READY", style="dim"))
            return

        widget.remove_class("sev-none")
        level = result.overall_risk
        widget.add_class(f"sev-{level.value}")

        line = Text()
        line.append(level.glyph, style=f"bold {level.color}")
        line.append("  ")
        line.append(level.value.upper(), style=f"bold {level.color}")
        line.append("   ")

        if result.findings:
            counts = result.finding_counts
            parts: list[str] = []
            for lvl in (RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW):
                n = counts[lvl]
                if n:
                    parts.append(f"{n} {lvl.value}")
            line.append(", ".join(parts))
        else:
            line.append("no issues", style="dim")

        line.append("   ")
        line.append(f"{result.token_count} tok", style="dim")
        if result.is_designer_prompt:
            line.append("   designer", style="dim italic")
        if result.has_high_or_worse:
            line.append("    ctrl+r to strip risks", style=f"dim {level.color}")

        widget.update(line)

    # ------------------------------------------------------------------ #
    # Scanning (auto + manual)
    # ------------------------------------------------------------------ #

    @on(TextArea.Changed, "#prompt-editor")
    def _on_editor_changed(self, event: TextArea.Changed) -> None:
        # Debounced auto-scan: rescan 350ms after the user stops typing
        if self._scan_timer is not None:
            self._scan_timer.stop()
        self._scan_timer = self.set_timer(0.35, self._perform_scan)

    async def action_scan(self) -> None:
        if self._scan_timer is not None:
            self._scan_timer.stop()
        await self._perform_scan(force_notify=True)

    async def _perform_scan(self, force_notify: bool = False) -> None:
        editor = self.query_one("#prompt-editor", TextArea)
        text = editor.text.strip()

        if not text:
            self.current_result = None
            self._refresh_status_line(None)
            await self._render_findings(None)
            self._hide_remix_history()
            return

        # Auto-switch pack if the user didn't lock one and the content suggests
        # a different pack would be more appropriate.
        if not self._pack_locked:
            detected = pack_for_text(text)
            if detected.name != self._pack.name:
                self._pack = detected
                self._refresh_top_bar()
                self._refresh_pane_label()
                if force_notify:
                    self.notify(f"Switched to pack: {self._pack.name}", severity="information")

        # Trace mode is prompt-safety specific.
        if self._pack.name == "prompt-safety":
            looks_like_trace = text.startswith(("{", "[")) or "messages" in text[:200].lower()
            if looks_like_trace:
                result = scan_trace(text)
            else:
                result = scan(text, self._pack)
        else:
            result = scan(text, self._pack)

        self.current_result = result
        self._refresh_status_line(result)
        await self._render_findings(result)
        # Note: do NOT hide the remix-history strip here. It persists across
        # scans as a record of what was last applied. It only hides when the
        # editor is fully cleared (action_clear or empty-text path above).

        if force_notify:
            if result.has_critical:
                self.notify("Critical issues. Fix before proceeding.", severity="error", timeout=4)
            elif result.has_high_or_worse:
                self.notify("High-risk findings. Review before proceeding.", severity="warning")
            elif result.findings:
                self.notify(result.status_line(), severity="information")
            else:
                self.notify("✓ Ready to send. ctrl+y to copy.", severity="information")

    async def _render_findings(self, result: ScanResult | None) -> None:
        container = self.query_one("#findings-scroll", VerticalScroll)
        # Await the removal so the registry is clean before we mount fresh widgets.
        # Without this, rapid clear-and-render cycles can race and produce DuplicateIds.
        await container.remove_children()

        if result is None:
            await container.mount(
                Static(
                    "Type or paste a prompt on the left. Scans run automatically.",
                    classes="empty-state",
                )
            )
            return

        if not result.findings:
            await container.mount(
                Static(
                    "✓ Ready to send.\n\nNo risks detected. ctrl+y to copy.",
                    classes="empty-state empty-state-clean",
                )
            )
            return

        # Collapse multiple findings of the same rule id into one card with extra excerpts.
        # Preserves severity ordering since result.findings is already sorted.
        collapsed: list = []
        by_id: dict[str, object] = {}
        for f in result.findings:
            existing = by_id.get(f.id)
            if existing is None:
                # Stash extras on the model; Pydantic v2 is fine with __setattr__
                object.__setattr__(f, "_extra_excerpts", [])
                by_id[f.id] = f
                collapsed.append(f)
            else:
                extras = getattr(existing, "_extra_excerpts", [])
                extras.append(f.excerpt)
                object.__setattr__(existing, "_extra_excerpts", extras)

        for f in collapsed[:25]:
            await container.mount(FindingCard(f))

        if len(collapsed) > 25:
            await container.mount(
                Static(
                    f"+ {len(collapsed) - 25} more (showing top 25 by severity)",
                    classes="findings-overflow",
                )
            )

    # ------------------------------------------------------------------ #
    # Remix — apply-and-record flow
    # ------------------------------------------------------------------ #

    async def action_remix(self) -> None:
        """Apply the safer-remix to the editor in place.

        The old behavior (show diff in a side panel) lost the user. The new
        flow: replace the editor content, auto-scan re-runs against the safer
        version, and the history strip below the editor shows what changed.
        Press ctrl+z to undo (TextArea's built-in history covers this).
        """
        # Ensure we have a fresh scan result for the CURRENT editor content.
        if self._scan_timer is not None:
            self._scan_timer.stop()
        await self._perform_scan(force_notify=False)

        result = self.current_result
        if result is None or not result.original_prompt.strip():
            self.notify("Nothing to remix.", severity="warning", timeout=3)
            return

        before_severity = result.overall_risk
        before_count = len(result.findings)

        remix = safe_remix(result)

        # Pack-doesn't-support-rewrite: the dispatcher returns the original
        # text with a one-note explanation. Clear any stale history from a
        # previous successful strip — leaving it up would be misleading.
        if remix.notes and "does not support rewriting" in remix.notes[0]:
            self._hide_remix_history()
            n_findings = len(result.findings)
            self.notify(
                f"The {self._pack.label} pack doesn't auto-rewrite. "
                f"You have {n_findings} finding{'' if n_findings == 1 else 's'} to review and edit manually.",
                severity="warning" if result.has_high_or_worse else "information",
                timeout=5,
            )
            return

        # No-op detection: rewriter returned the same text. Distinguish between
        # "nothing to strip" (clean prompt) and "had findings but couldn't fix
        # them" (e.g. PII findings that need user judgment).
        if remix.remixed.strip() == result.original_prompt.strip():
            self._hide_remix_history()
            if result.findings:
                n = len(result.findings)
                self.notify(
                    f"Strip made no changes. "
                    f"{n} finding{'' if n == 1 else 's'} still need{'s' if n == 1 else ''} your attention — "
                    f"review and edit manually.",
                    severity="warning" if result.has_high_or_worse else "information",
                    timeout=5,
                )
            else:
                self.notify(
                    "✓ Ready to send. No risks to strip.",
                    severity="information",
                    timeout=4,
                )
            return

        # Apply: replace the entire document via the edit API so the change
        # goes through TextArea's undo history (ctrl+z restores the original).
        # load_text() does not register with undo; replace() does.
        editor = self.query_one("#prompt-editor", TextArea)
        end_location = editor.document.end
        editor.replace(remix.remixed, start=(0, 0), end=end_location)

        # Force a re-scan now so the after-severity is correct in the notification.
        # (load_text triggers TextArea.Changed → debounced scan, but we want the
        # answer immediately for the toast.)
        if self._scan_timer is not None:
            self._scan_timer.stop()
        await self._perform_scan(force_notify=False)

        after_result = self.current_result
        after_severity = after_result.overall_risk if after_result else before_severity
        after_count = len(after_result.findings) if after_result else 0

        # Update the history strip with the specific changes.
        self._show_remix_history(
            notes=remix.notes,
            before_sev=before_severity,
            after_sev=after_severity,
            before_count=before_count,
            after_count=after_count,
        )

        # Headline notification.
        severity_changed = before_severity != after_severity
        count_delta = before_count - after_count
        if severity_changed or count_delta > 0:
            msg = (
                f"Applied {len(remix.notes)} change{'s' if len(remix.notes) != 1 else ''}. "
                f"{before_severity.value.upper()} → {after_severity.value.upper()}, "
                f"{before_count} → {after_count} findings. ctrl+z to undo."
            )
            self.notify(msg, severity="information", timeout=6)
        else:
            self.notify(
                f"Applied {len(remix.notes)} change{'s' if len(remix.notes) != 1 else ''}. "
                f"ctrl+z to undo.",
                severity="information",
                timeout=4,
            )

    async def action_preview_remix(self) -> None:
        """Open the side-by-side preview modal. Phase 2: review before apply."""
        if self._scan_timer is not None:
            self._scan_timer.stop()
        await self._perform_scan(force_notify=False)

        result = self.current_result
        if result is None or not result.original_prompt.strip():
            self.notify("Nothing to remix.", severity="warning", timeout=3)
            return

        remix = safe_remix(result)
        if remix.remixed.strip() == result.original_prompt.strip():
            self.notify("No changes needed.", severity="information", timeout=3)
            return

        before_severity = result.overall_risk
        before_count = len(result.findings)

        def _on_decision(decision: str | None) -> None:
            if decision == "apply":
                editor = self.query_one("#prompt-editor", TextArea)
                end_location = editor.document.end
                editor.replace(remix.remixed, start=(0, 0), end=end_location)
                self._show_remix_history(
                    notes=remix.notes,
                    before_sev=before_severity,
                    after_sev=before_severity,  # will be updated by re-scan
                    before_count=before_count,
                    after_count=before_count,
                )
                self.notify("Applied. ctrl+z to undo.", severity="information", timeout=3)

        self.push_screen(
            RemixPreview(
                original=result.original_prompt,
                rewritten=remix.remixed,
                notes=remix.notes,
                before_severity=before_severity,
                before_count=before_count,
            ),
            callback=_on_decision,
        )

    def _show_remix_history(
        self,
        notes: list[str],
        before_sev: RiskLevel,
        after_sev: RiskLevel,
        before_count: int,
        after_count: int,
    ) -> None:
        """Render the persistent history strip below the editor."""
        strip = self.query_one("#remix-history", VerticalScroll)
        strip.remove_class("remix-history-hidden")

        content = self.query_one("#remix-history-content", Static)
        body = Text()
        # Headline: "LAST STRIP · CRITICAL → LOW · 5 → 0 findings"
        body.append("LAST STRIP  ", style="bold")
        body.append(before_sev.value.upper(), style=f"bold {before_sev.color}")
        body.append(" → ")
        body.append(after_sev.value.upper(), style=f"bold {after_sev.color}")
        body.append(f"   {before_count} → {after_count} findings", style="dim")
        body.append("\n")
        # Note list. Lines starting with the hint marker get a different style:
        # they read as a soft question under the removal, not a separate entry.
        for n in notes:
            if n.lstrip().startswith("↳"):
                hint = n.lstrip().removeprefix("↳").strip()
                body.append("       ", style="dim")
                body.append("↳ ", style="dim")
                body.append(f"{hint}\n", style="italic dim")
            else:
                body.append("  · ", style="dim")
                body.append(f"{n}\n")
        content.update(body)

    def _hide_remix_history(self) -> None:
        strip = self.query_one("#remix-history", VerticalScroll)
        strip.add_class("remix-history-hidden")
        content = self.query_one("#remix-history-content", Static)
        content.update("")

    # ------------------------------------------------------------------ #
    # Copy editor contents
    # ------------------------------------------------------------------ #

    def action_copy_editor(self) -> None:
        editor = self.query_one("#prompt-editor", TextArea)
        text = editor.text
        if not text.strip():
            self.notify("Editor is empty.", severity="warning", timeout=2)
            return
        try:
            pyperclip.copy(text)
            self.notify(
                f"Copied {len(text)} character{'s' if len(text) != 1 else ''} to clipboard.",
                severity="information",
                timeout=2,
            )
        except Exception as e:
            self.notify(f"Clipboard error: {e}", severity="error", timeout=4)

    # ------------------------------------------------------------------ #
    # Templates
    # ------------------------------------------------------------------ #

    def action_open_templates(self) -> None:
        def _apply(tpl: Template | None) -> None:
            if not tpl:
                return
            editor = self.query_one("#prompt-editor", TextArea)
            editor.text = tpl.body
            self.notify(f"Loaded template: {tpl.title}", severity="information")
            # Auto-scan triggers via TextArea.Changed

        # User templates load fresh from disk each time the picker opens, so
        # external edits are picked up without restarting the app.
        user_templates = load_user_templates(self._pack.name)
        builtin_templates = list(self._pack.templates)
        self.push_screen(
            TemplatePicker(user_templates, builtin_templates),
            callback=_apply,
        )

    def action_save_template(self) -> None:
        """Save the current editor content as a user template for this pack."""
        editor = self.query_one("#prompt-editor", TextArea)
        body = editor.text.strip()
        if not body:
            self.notify("Nothing to save — the editor is empty.", severity="warning", timeout=3)
            return

        # Pre-fill the title prompt with the first line, trimmed.
        first_line = body.splitlines()[0].strip()
        if first_line.startswith("#"):
            first_line = first_line.lstrip("#").strip()
        prefill = first_line[:60]

        pack_name = self._pack.name

        def _on_title(title: str | None) -> None:
            if not title:
                return
            if template_exists(pack_name, title):
                def _on_overwrite(confirm: bool) -> None:
                    if confirm:
                        self._do_save(pack_name, title, body, overwrite=True)
                    else:
                        self.notify("Save cancelled.", severity="information", timeout=2)

                path = pack_templates_dir(pack_name) / f"{slugify(title)}.md"
                self.push_screen(OverwriteConfirm(path), callback=_on_overwrite)
            else:
                self._do_save(pack_name, title, body, overwrite=False)

        self.push_screen(TitlePrompt(prefill=prefill), callback=_on_title)

    def _do_save(self, pack_name: str, title: str, body: str, overwrite: bool) -> None:
        try:
            result = save_user_template(
                pack_name=pack_name,
                title=title,
                body=body,
                overwrite=overwrite,
            )
            verb = "Updated" if result.overwrote else "Saved"
            self.notify(
                f"{verb} template: {result.title}\n→ {result.path}",
                severity="information",
                timeout=4,
            )
        except (OSError, ValueError, FileExistsError) as e:
            self.notify(f"Save failed: {e}", severity="error", timeout=5)

    # ------------------------------------------------------------------ #
    # File load
    # ------------------------------------------------------------------ #

    def action_load_file(self) -> None:
        def _loaded(path: Path | None) -> None:
            if not path:
                return
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                editor = self.query_one("#prompt-editor", TextArea)
                editor.text = text
                self.notify(f"Loaded {path.name}", severity="information")
            except OSError as e:
                self.notify(f"Failed to read file: {e}", severity="error")

        self.push_screen(QuickLoad(), callback=_loaded)

    # ------------------------------------------------------------------ #
    # Theme toggle
    # ------------------------------------------------------------------ #

    def action_toggle_theme(self) -> None:
        self.theme = "high-contrast" if self.theme == "standard" else "standard"
        self.notify(f"Theme: {self.theme}", severity="information", timeout=2)

    # ------------------------------------------------------------------ #
    # Misc
    # ------------------------------------------------------------------ #

    async def action_clear(self) -> None:
        editor = self.query_one("#prompt-editor", TextArea)
        if editor.text:
            editor.clear()
            self.current_result = None
            self._refresh_status_line(None)
            await self._render_findings(None)
            self._hide_remix_history()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())
