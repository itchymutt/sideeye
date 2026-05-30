# SideEye

A local text linter with pluggable rule packs. No network calls, no model
calls, no telemetry. Just regex and Python.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Textual 8+](https://img.shields.io/badge/textual-8%2B-4ecdc4)
![Tests](https://img.shields.io/badge/tests-88%20passing-green)

---

## What it catches

SideEye ships with three rule packs. Add your own in a single Python file.

**`prompt-safety`** (default) — LLM prompt and agent-trace failure modes:
- Direct prompt injection ("ignore all previous instructions")
- Jailbreaks / DAN / persona overrides
- Role escalation ("you are the ultimate X")
- PII and secrets (emails, AWS keys, GitHub tokens, API keys)
- Data exfiltration attempts ("repeat your system prompt")
- Structured-tag injection
- Token bombs (repetition attacks)
- Copyright risk (named living artists, in designer-mode contexts)
- Brand impersonation
- Overconfident or under-constrained creative prompts
- Style attribution to unknown people (soft signal)

**`markdown`** — Markdown style, accessibility, and hygiene:
- Missing image alt text
- Heading-level jumps
- Lazy link text ("click here", "read more")
- Bare URLs in prose
- TODO/FIXME left in the document
- Trailing whitespace, multiple blank lines

**`personal-info`** — User-configured sensitive strings. Reads from
`~/.config/sideeye/personal.toml`. Use this for your real name, internal
project codenames, client names under NDA, etc. See
[examples/personal.toml.example](examples/personal.toml.example).

---

## Install

```bash
pipx install sideeye
sideeye
```

From source:

```bash
git clone https://github.com/yourname/sideeye
cd sideeye
pip install -e ".[dev]"
sideeye
```

---

## TUI

```bash
sideeye                          # default pack auto-detected from content
sideeye --pack markdown          # lock to a specific pack
sideeye --pack personal-info     # check for your configured PII
```

Type or paste text. Scans run automatically 350ms after you stop typing.
Findings appear sorted by severity. Press `ctrl+r` for a deterministic safer
rewrite. The remix replaces your editor content in place — press `ctrl+z` to
undo, `ctrl+y` to copy.

For a deliberate, side-by-side review before applying: `ctrl+shift+r`.

---

## Headless

```bash
sideeye packs                                  # list available packs
sideeye scan "your text here"                  # pretty output
sideeye scan -p markdown < README.md           # pipe with a specific pack
sideeye scan --json < prompt.txt               # machine-readable
sideeye scan --file template.prompt            # pack auto-detected from extension
```

### CI gate

```bash
# Exit 1 if any HIGH+ finding (default threshold)
sideeye check < prompt.txt

# Tighter gate — fail on any finding
sideeye check --fail-on low < prompt.txt

# Pack-specific gate
sideeye check --pack markdown -f README.md

# Quiet mode for hooks (exit code only)
sideeye check -q "ignore all previous instructions"
```

Exit codes: `0` (OK), `1` (threshold met), `2` (malformed input).
Drop this into a pre-commit hook, PR check, or release gate.

---

## What gets flagged (and what doesn't)

SideEye catches **documented attack patterns**, not arbitrary text. The
prompt-safety rules fire on specific known phrases — DAN, "ignore all
previous instructions", common API key prefixes — not on every name or
capitalized word. This is intentional: a linter that flags every name is a
linter that gets ignored.

For project-specific concerns (your real name, internal codenames,
confidential client names), use the **personal-info** pack:

```bash
# 1. Copy the example config and edit it
mkdir -p ~/.config/sideeye
cp examples/personal.toml.example ~/.config/sideeye/personal.toml
$EDITOR ~/.config/sideeye/personal.toml

# 2. Run with --pack personal-info to check your text against it
sideeye --pack personal-info
```

The config is TOML. Strings are matched literally, regex are full Python
regex. Categories you define become the finding labels. Example:

```toml
[strings]
names = ["Your Real Name", "Family Member"]
clients = ["Confidential Client Inc"]
codenames = ["Project Sparrow"]

[regex]
internal_ids = ["\\bACME-\\d{4,}\\b"]
```

---

## Keys (TUI)

| Key | Action |
|---|---|
| `ctrl+s` | scan now (auto-scan is on by default) |
| `ctrl+r` | safe rewrite — applies in place |
| `ctrl+shift+r` | preview the remix side-by-side first |
| `ctrl+y` | copy editor contents to clipboard |
| `ctrl+z` | undo (built into the editor) |
| `ctrl+t` | template picker (your templates first, then built-in) |
| `ctrl+shift+s` | save current editor content as a user template |
| `ctrl+v` | paste from clipboard |
| `ctrl+l` | load from file |
| `ctrl+shift+t` | toggle high-contrast theme |
| `esc` | clear editor / dismiss modal |
| `f1` | help overlay |
| `ctrl+q` | quit |

## Templates

SideEye ships with a small library of built-in starter prompts per pack
(critique, moodboard, error-message, etc.). More importantly, **you can save
your own**.

### Saving a template

Type or paste a prompt you want to reuse. Press `ctrl+shift+s`. Enter a title.
Done. The file lives at:

```
~/.config/sideeye/templates/<pack-name>/<slug>.md
```

It's plain markdown with optional YAML frontmatter:

```markdown
---
title: My Daily Critique Prompt
category: critique
description: My personalized version of the design crit starter
---

You are a senior product designer with 12 years of experience...
```

You can edit these files in any editor. SideEye reads them fresh every time
the picker opens.

### Browsing templates

In the TUI: `ctrl+t` opens the picker. Your saved templates appear at the top
under `── Mine ──`, marked with a green dot. Built-ins appear below.

From the command line:

```bash
sideeye templates                    # list all user templates by pack
sideeye templates --pack markdown    # filter to a specific pack
sideeye templates --path             # print the templates root directory
```

### Sharing templates with a team

Templates are files in a directory. Point sideeye at a different directory
with the `SIDEEYE_TEMPLATES_DIR` env var:

```bash
SIDEEYE_TEMPLATES_DIR=~/team-prompts sideeye
```

For real team sync, point that env var at a git repo your whole team clones.
SideEye stays agnostic to where the files come from.

---

## How ctrl+r works

ctrl+r is a **safety filter**, not a creative coach. It removes documented
risky phrases, redacts confirmed PII, and tidies the grammatical seams left
behind. It does not rewrite your prompt to be "better." That's your job.

Specifically, it does two kinds of changes:

**Redacts (replaces with `[REDACTED:kind]`):**

- Email addresses → `[REDACTED:email]`
- AWS access keys (`AKIA...`) → `[REDACTED:aws-key]`
- GitHub tokens (`ghp_...`, `gho_...`) → `[REDACTED:github-token]`
- GitLab tokens (`glpat_...`) → `[REDACTED:gitlab-token]`
- Hugging Face tokens (`hf_...`) → `[REDACTED:hf-token]`
- Google API keys (`AIza...`) → `[REDACTED:google-api-key]`
- Stripe keys (`sk_...`, `pk_...`) → `[REDACTED:stripe-key]`
- Phone numbers → `[REDACTED:phone]`

**Strips (removes entirely):**

1. Direct injection ("ignore all previous instructions")
2. Jailbreak / persona overrides (DAN, developer mode, etc.) — including
   trailing role descriptions
3. Totalizing role assignments ("you are the ultimate X")
4. Named-artist style references (in designer-mode contexts)
5. "Make it perfect" / "do not hold back" type phrases
6. Hyperbolic filler ("super", "absolutely", "mind-blowing", etc.)
7. Politeness padding ("please", "kindly")

What it does NOT do:

- Substitute pre-baked replacement phrases for stripped content (the old
  behavior produced generic-feeling output)
- Prepend a "you are a helpful assistant" guardrail (boilerplate erodes
  signal)
- Try to understand your creative intent (regex can't, and the LLM you're
  about to hand the prompt to is better at it anyway)

The TUI applies the strip in place and shows a change log below the editor
with each removed phrase quoted in your own words. For translatable shortcuts
(jailbreak / role / "make it perfect" / artist names) the log appends a soft
question pointing at what you might have actually meant. Press `ctrl+z` to
revert, `ctrl+y` to copy the stripped prompt.

For project-specific concerns the safety filter can't know about (your name,
internal codenames, NDA client names), use the `personal-info` pack with a
config at `~/.config/sideeye/personal.toml`. It does the same redaction with
your custom strings.

---

## Project structure

```
sideeye/
├── pyproject.toml
├── README.md
├── examples/
│   └── personal.toml.example      # config template for personal-info pack
├── src/sideeye/
│   ├── models.py                  # Severity, Finding, ScanResult
│   ├── packs/
│   │   ├── base.py                # Pack protocol, scan() engine
│   │   ├── registry.py            # built-in pack registration
│   │   ├── prompt_safety.py       # LLM prompt rules + rewriter
│   │   ├── markdown.py            # markdown style/a11y rules
│   │   └── personal_info.py       # user-configured PII rules
│   ├── scanner.py                 # scan_text(text, pack) orchestrator
│   ├── remixer.py                 # rewrite dispatcher
│   ├── entry_points.py            # CLI: packs, scan, check, TUI
│   └── tui/
│       ├── app.py
│       ├── styles.tcss
│       └── widgets/finding_card.py
└── tests/                          # 88 tests
```

---

## Adding a custom pack

A pack is a single Python file. Subclass `BasePack`, declare your rules.
See `src/sideeye/packs/markdown.py` for a 200-line working example, or
`src/sideeye/packs/personal_info.py` for one that reads user config.

```python
from dataclasses import dataclass, field
from sideeye.packs.base import BasePack, PackRule
from sideeye.models import Category, Severity
import re

@dataclass
class CommitMessagePack(BasePack):
    name: str = "commit"
    label: str = "Commit Message"
    description: str = "Lint git commit messages for repo conventions."
    file_extensions: tuple[str, ...] = ()
    categories: list = field(default_factory=lambda: [
        Category(id="format", label="Format"),
    ])
    rules: list = field(default_factory=lambda: [
        PackRule(
            id="wip",
            category="format",
            severity=Severity.HIGH,
            message="WIP commit messages should not land on main.",
            suggestion="Rewrite with a descriptive subject before merging.",
            pattern=re.compile(r"(?i)^(wip|fixup|squash|temp|tmp)\b"),
        ),
        # ... more rules
    ])
```

Register it in `src/sideeye/packs/registry.py`:

```python
BUILTIN_PACKS["commit"] = CommitMessagePack()
```

Then `sideeye --pack commit` works everywhere.

---

## Design principles

- **Local first.** Your text never leaves the machine. No telemetry, no
  analytics, no LLM calls for analysis.
- **Rules are inspectable.** Every detection is a regex or a small Python
  function. No black boxes.
- **Keyboard-driven.** Every action has a keybinding. The mouse is optional.
- **CLI is first-class.** The TUI is the playground. The CLI is the workhorse.
  Pipe-friendly, JSON-emitting, exit-code-respecting.
- **Quiet by default.** Findings are clinical because trust is the product.
- **Documented attacks, not arbitrary content.** A linter that fires on every
  name is a linter that gets ignored. Use the personal-info pack for
  project-specific concerns.

---

## License

MIT.
