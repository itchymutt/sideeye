# SideEye

SideEye is a local text linter for prompts, markdown, and sensitive text. It runs entirely on your machine — no network calls, no model calls, no telemetry. Comes with a TUI and a CLI. Just regex and Python.

---

## Install

With `pipx`:

```bash
pipx install sideeye
sideeye
```

From source:

```bash
git clone https://github.com/itchymutt/sideeye
cd sideeye
pip install -e ".[dev]"
sideeye
```

---

## Quick start

### TUI

```bash
sideeye                          # auto-detect pack from content
sideeye --pack markdown          # markdown-only checks
sideeye --pack personal-info     # check against your PII config
```

- Auto-scans 350ms after you stop typing
- Findings sorted by severity
- `ctrl+r` → safer rewrite in place
- `ctrl+shift+r` → side-by-side preview before applying

### CLI

```bash
sideeye packs                                  # list packs
sideeye scan "your text here"                  # pretty output
sideeye scan -p markdown < README.md           # specific pack
sideeye scan --json < prompt.txt               # JSON output
sideeye scan --file template.prompt            # auto-detect pack
```

### CI / hooks

```bash
# Exit 1 if any HIGH+ finding (default)
sideeye check < prompt.txt

# Fail on any finding
sideeye check --fail-on low < prompt.txt

# Pack-specific gate
sideeye check --pack markdown -f README.md

# Quiet mode (exit code only)
sideeye check -q "ignore all previous instructions"
```

Exit codes: `0` (OK), `1` (threshold met), `2` (malformed input).

---

## Packs

### `prompt-safety` (default)

Looks for documented LLM failure patterns, including:

- Direct prompt injection (`"ignore all previous instructions"`, DAN, persona overrides)
- Role escalation (`"you are the ultimate X"`)
- Data exfiltration attempts (`"repeat your system prompt"`)
- Common API key and token formats
- Named living artists (designer-style prompts)
- Brand impersonation and over-the-top “make it perfect” prompts

It matches known patterns, not every proper noun, so it doesn’t light up on every capitalized word.

### `markdown`

Checks markdown for:

- Missing image alt text
- Heading-level jumps
- Lazy link text (`"click here"`, `"read more"`)
- Bare URLs in prose
- `TODO` / `FIXME`
- Trailing whitespace and extra blank lines

### `personal-info`

Matches PII and project-specific strings from:

```text
~/.config/sideeye/personal.toml
```

Use it for your real name, internal codenames, NDA client names, etc.

Example:

```toml
[strings]
names = ["Your Real Name", "Family Member"]
clients = ["Confidential Client Inc"]
codenames = ["Project Sparrow"]

[regex]
internal_ids = ["\\bACME-\\d{4,}\\b"]
```

---

## Safer rewrites (`ctrl+r`)

`ctrl+r` is a safety filter, not a prompt engineer. It:

- **Redacts** confirmed PII and keys (emails, AWS keys, GitHub/GitLab/HF/Google/Stripe tokens, phone numbers) as `[REDACTED:kind]`
- **Strips** known risky phrasing (direct injections, jailbreak framing, “make it perfect”, totalizing roles, named-artist styles in designer contexts, etc.)
- **Tidies** seams left behind so the text still parses

It does *not* add boilerplate, prepend guardrails, or try to “improve” your prompt.

For project-specific strings, run with `--pack personal-info` and a `personal.toml` as above.

---

## Custom packs

A pack is a single Python file subclassing `BasePack` with a list of regex-powered rules. Once you register it, it works everywhere:

```bash
sideeye --pack your-pack-name
```

See `src/sideeye/packs/markdown.py` and `src/sideeye/packs/personal_info.py` for working examples.

---

## Design principles

- Local first: text never leaves your machine.
- No black boxes: every rule is inspectable Python or regex.
- Keyboard-first: every action has a keybinding.
- CLI-first: pipe-friendly, JSON output, exit codes for automation.
- Quiet, clinical findings: tuned to documented attacks, not arbitrary content.

---

## License

MIT.
