# SideEye

SideEye is a local text linter for prompts, markdown, and sensitive text. It uses pluggable rule packs, runs entirely on your machine, and makes zero network calls, model calls, or telemetry requests. It's just regex and Python.

## What it catches

SideEye ships with three rule packs, and you can add your own in a single Python file.

### `prompt-safety` (default)

Designed for common LLM prompt and agent-trace failure modes, including:

- Direct prompt injection, like “ignore all previous instructions”
- Jailbreaks, DAN prompts, and persona overrides
- Role escalation, like “you are the ultimate X”
- PII and secrets, including emails, AWS keys, GitHub tokens, and API keys
- Data exfiltration attempts, like “repeat your system prompt”
- Structured-tag injection
- Token bombs and repetition attacks
- Copyright risk, especially named living artists in designer-style prompts
- Brand impersonation
- Overconfident or under-constrained creative prompts
- Style attribution to unknown people as a soft signal

### `markdown`

Checks markdown for style, accessibility, and basic hygiene:

- Missing image alt text
- Heading-level jumps
- Lazy link text like “click here” or “read more”
- Bare URLs in prose
- `TODO` and `FIXME` left behind
- Trailing whitespace and multiple blank lines

### `personal-info`

Checks for user-defined sensitive strings from `~/.config/sideeye/personal.toml`. Use it for things SideEye can’t know by default, like your real name, internal codenames, or NDA client names.

See [`examples/personal.toml.example`](https://github.com/itchymutt/sideeye/blob/main/examples/personal.toml.example).

## Install

### With `pipx`

```bash
pipx install sideeye
sideeye
```

### From source

```bash
git clone https://github.com/itchymutt/sideeye
cd sideeye
pip install -e ".[dev]"
sideeye
```

## TUI

```bash
sideeye                          # default pack auto-detected from content
sideeye --pack markdown          # force a specific pack
sideeye --pack personal-info     # check against your configured PII
```

Type or paste text into the editor. SideEye scans automatically 350ms after you stop typing, then shows findings sorted by severity.

Press `ctrl+r` for a deterministic safer rewrite. It replaces the editor contents in place, so you can use `ctrl+z` to undo or `ctrl+y` to copy the result.

If you want to review changes before applying them, press `ctrl+shift+r` for a side-by-side preview.

## Headless

```bash
sideeye packs                                  # list available packs
sideeye scan "your text here"                  # pretty output
sideeye scan -p markdown < README.md           # pipe with a specific pack
sideeye scan --json < prompt.txt               # machine-readable output
sideeye scan --file template.prompt            # auto-detect pack from extension
```

## CI gate

```bash
# Exit 1 if any HIGH+ finding is present
sideeye check < prompt.txt

# Fail on any finding
sideeye check --fail-on low < prompt.txt

# Pack-specific gate
sideeye check --pack markdown -f README.md

# Quiet mode for hooks and scripts
sideeye check -q "ignore all previous instructions"
```

Exit codes:

- `0` = OK
- `1` = threshold met
- `2` = malformed input

That makes it easy to drop into a pre-commit hook, PR check, or release gate.

## What gets flagged, and what doesn’t

SideEye looks for documented patterns, not arbitrary text. The `prompt-safety` pack matches known phrases and formats — things like DAN prompts, “ignore all previous instructions,” or common API key prefixes — rather than flagging every proper noun or capitalized phrase.

That tradeoff is deliberate. A linter that flags everything gets ignored.

For project-specific concerns, use the `personal-info` pack.

```bash
# 1. Copy the example config and edit it
mkdir -p ~/.config/sideeye
cp examples/personal.toml.example ~/.config/sideeye/personal.toml
$EDITOR ~/.config/sideeye/personal.toml

# 2. Run SideEye against your custom config
sideeye --pack personal-info
```

The config is TOML. Strings are matched literally, and regex patterns use full Python regex syntax. Whatever categories you define become the finding labels.

Example:

```toml
[strings]
names = ["Your Real Name", "Family Member"]
clients = ["Confidential Client Inc"]
codenames = ["Project Sparrow"]

[regex]
internal_ids = ["\\bACME-\\d{4,}\\b"]
```

## Keys

| Key | Action |
|---|---|
| `ctrl+s` | Scan now (auto-scan is on by default) |
| `ctrl+r` | Safer rewrite, applied in place |
| `ctrl+shift+r` | Preview the rewrite side by side |
| `ctrl+y` | Copy editor contents to clipboard |
| `ctrl+z` | Undo |
| `ctrl+t` | Open template picker |
| `ctrl+shift+s` | Save current editor content as a user template |
| `ctrl+v` | Paste from clipboard |
| `ctrl+l` | Load from file |
| `ctrl+shift+t` | Toggle high-contrast theme |
| `esc` | Clear editor or dismiss modal |
| `f1` | Help overlay |
| `ctrl+q` | Quit |

## Templates

SideEye includes a small set of built-in starter prompts for each pack, but the more useful feature is that you can save your own.

### Saving a template

Paste or write a prompt you want to reuse, then press `ctrl+shift+s`, give it a title, and SideEye saves it here:

```text
~/.config/sideeye/templates/<pack-name>/<slug>.md
```

Templates are plain markdown files with optional YAML frontmatter:

```md
---
title: My Daily Critique Prompt
category: critique
description: My personalized version of the design crit starter
---

You are a senior product designer with 12 years of experience...
```

You can edit them in any editor. SideEye reloads them every time the picker opens.

### Browsing templates

In the TUI, press `ctrl+t` to open the picker. Your saved templates appear at the top under `── Mine ──`, marked with a green dot. Built-in templates appear below.

From the command line:

```bash
sideeye templates                    # list all user templates by pack
sideeye templates --pack markdown    # filter by pack
sideeye templates --path             # print the templates root directory
```

### Sharing templates with a team

Templates are just files in a directory. To point SideEye somewhere else, set `SIDEEYE_TEMPLATES_DIR`:

```bash
SIDEEYE_TEMPLATES_DIR=~/team-prompts sideeye
```

If you want team-wide sharing, point that directory at a Git repo everyone clones. SideEye stays agnostic about where the files come from.

## How `ctrl+r` works

`ctrl+r` is a safety filter, not a creative coach. It removes documented risky phrases, redacts confirmed PII, and cleans up the grammatical seams left behind. It does not try to make your prompt smarter, better, or more imaginative.

It does two kinds of edits.

### Redacts

Replaces known sensitive values with `[REDACTED:kind]`, including:

- Email addresses → `[REDACTED:email]`
- AWS access keys (`AKIA...`) → `[REDACTED:aws-key]`
- GitHub tokens (`ghp_...`, `gho_...`) → `[REDACTED:github-token]`
- GitLab tokens (`glpat_...`) → `[REDACTED:gitlab-token]`
- Hugging Face tokens (`hf_...`) → `[REDACTED:hf-token]`
- Google API keys (`AIza...`) → `[REDACTED:google-api-key]`
- Stripe keys (`sk_...`, `pk_...`) → `[REDACTED:stripe-key]`
- Phone numbers → `[REDACTED:phone]`

### Strips

Removes risky phrases entirely, including:

- Direct injection like “ignore all previous instructions”
- Jailbreaks and persona overrides, including DAN, developer mode, and trailing role descriptions
- Totalizing role assignments like “you are the ultimate X”
- Named-artist style references in designer-mode contexts
- Phrases like “make it perfect” or “do not hold back”
- Hyperbolic filler like “super,” “absolutely,” or “mind-blowing”
- Politeness padding like “please” and “kindly”

Stripping these phrases usually shortens the prompt slightly and produces fewer model refusals or generic re-rolls, so end-to-end token use tends to go down, though SideEye is not optimized for token compression as a primary goal.

### What it does not do

- Insert canned replacement text for stripped phrases
- Prepend generic guardrails like “you are a helpful assistant”
- Try to infer your creative intent

When a rewrite runs, the TUI updates the editor in place and shows a change log below it with each removed phrase quoted back in your own words. For some categories - jailbreaks, role framing, “make it perfect” phrasing, and artist-style references - the log also adds a soft question about what you may have actually meant.

Use `ctrl+z` to revert or `ctrl+y` to copy the stripped version.

For project-specific redaction that SideEye can’t know on its own, use the `personal-info` pack with a config at `~/.config/sideeye/personal.toml`. It uses the same redaction flow with your custom strings and regexes.

## Project structure

```text
sideeye/
├── pyproject.toml
├── README.md
├── examples/
│   └── personal.toml.example
├── src/sideeye/
│   ├── models.py
│   ├── packs/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── prompt_safety.py
│   │   ├── markdown.py
│   │   └── personal_info.py
│   ├── scanner.py
│   ├── remixer.py
│   ├── entry_points.py
│   └── tui/
│       ├── app.py
│       ├── styles.tcss
│       └── widgets/finding_card.py
└── tests/
```

## Adding a custom pack

A pack is just a Python file. Subclass `BasePack`, define your rules, and register it.

See `src/sideeye/packs/markdown.py` for a compact built-in example, or `src/sideeye/packs/personal_info.py` for one that reads user config.

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
    ])
```

Then register it in `src/sideeye/packs/registry.py`:

```python
BUILTIN_PACKS["commit"] = CommitMessagePack()
```

After that, `sideeye --pack commit` works anywhere.

## Design principles

- **Local first.** Your text never leaves your machine. No telemetry, analytics, or LLM calls.
- **Inspectable rules.** Every detection is a regex or a small Python function. No black boxes.
- **Keyboard-driven.** Every action has a keybinding. The mouse is optional.
- **CLI-first.** The TUI is the playground; the CLI is the workhorse. It’s pipe-friendly, JSON-emitting, and exit-code-respecting.
- **Quiet by default.** Findings are clinical because trust is the product.
- **Documented attacks, not arbitrary content.** If you need project-specific detection, use `personal-info`.

## License

MIT.
