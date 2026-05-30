# SideEye Roadmap

For future-you (or future-collaborators) walking back into this project cold.

This is not a wishlist. Each item has a real motivation, an estimated cost,
and an explicit reason why it's queued vs deferred vs rejected. Pick the
top of "Ready to build" and go.

---

## Where we are right now

- **Version:** 0.2.0
- **Tests:** 127 passing
- **Packs:** `prompt-safety` (default), `markdown`, `personal-info`
- **TUI features:** auto-scan, strip risks (`ctrl+r`), strip preview
  (`ctrl+shift+r`), copy (`ctrl+y`), template picker (`ctrl+t`),
  save template (`ctrl+shift+s`)
- **CLI:** `sideeye`, `sideeye scan`, `sideeye check`, `sideeye packs`,
  `sideeye templates`
- **What works well:** the safety-filter pitch is honest (we strip, we
  redact, we don't pretend to be a creative coach), the personal-info pack
  redacts configured PII, the prompt-safety pack now redacts emails / AWS
  keys / GitHub tokens / etc.
- **Open issues:** see "Known papercuts" below.

---

## Ready to build (priority order)

Each of these is scoped, designed, and ready to execute. The estimates are
honest (AI-pair time, not solo-human time).

### 1. History (opt-in) — ~2 hours

**Why:** Turns the tool from a one-shot linter into a learning loop. You
keep typing the same kind of prompt; history shows you the pattern; you
save a template that addresses it; the loop closes.

**Shape:**

- Config flag in `~/.config/sideeye/config.toml`:
  ```toml
  [history]
  enabled = true
  retention_days = 30
  ```
- Each `ctrl+r` (or every scan if config says `log_all_scans = true`) appends
  a JSONL row to `~/.local/share/sideeye/history.jsonl`
- Row schema: `{timestamp, pack, prompt_hash, prompt_preview (first 200 chars),
  severity_before, severity_after, finding_counts, stripped, redacted}`
- New CLI: `sideeye history` (list recent), `--grep PATTERN`, `--stats`,
  `--purge`

**Hardest decision:** what gets logged. Default to "ctrl+r events only"
because logging every scan is high-volume and lower-signal. Make
`log_all_scans` opt-in for users who want full visibility.

**Files to touch:**
- New: `src/sideeye/history.py` (writer + reader)
- `src/sideeye/entry_points.py` (new subcommand)
- `src/sideeye/tui/app.py` (call history.log() in action_remix)
- New: `tests/test_history.py`

**Privacy notes:**
- Off by default. Document the implications when enabled.
- History file is local only. Never synced.
- `sideeye history --purge` for hard delete.

### 2. Multi-pack scan mode — ~1.5 hours

**Why:** The "user is in pack A but their content has pack B's concerns"
problem (which I deferred earlier). Right now if you're in `prompt-safety`
and your text has internal codenames, you have to know to switch packs.

**Shape:**

- New flag: `sideeye --multi-pack`, `sideeye scan --multi-pack`
- Runs every configured pack against the input; merges findings
- TUI: top bar shows `pack: multi (prompt-safety + personal-info)` when active
- Each finding card shows its source pack as a small dim label

**Hardest decision:** how to merge severity. Use max — if any pack says
HIGH, status is HIGH.

**Files to touch:**
- `src/sideeye/scanner.py` (new `scan_with_multiple_packs`)
- `src/sideeye/entry_points.py` (flag wiring)
- `src/sideeye/tui/app.py` (multi-pack mode + UI labels)
- `src/sideeye/packs/registry.py` (helper: `all_user_active_packs()`)

### 3. Template paths from config — ~30 minutes

**Why:** Currently `SIDEEYE_TEMPLATES_DIR` is one path. Real teams want
"my personal templates + my team's templates." A list in config solves
this without changing the TUI.

**Shape:**

```toml
# ~/.config/sideeye/config.toml
[templates]
paths = [
  "~/.config/sideeye/templates",      # personal (default)
  "~/Code/team-prompts/sideeye",      # team
]
```

`load_user_templates(pack)` iterates all configured paths, dedupes by slug,
sorts by mtime. Templates from later paths shadow earlier ones (so personal
overrides team).

**Files to touch:**
- New: `src/sideeye/config.py` (shared config loader)
- `src/sideeye/user_templates.py` (accept multiple paths)
- `tests/test_user_templates.py` (new tests)

### 4. Pre-commit hook — ~45 minutes

**Why:** The `sideeye check` CLI was designed for CI gates but most users
don't actually wire it up. A pre-commit config makes it trivial.

**Shape:**

- New file: `.pre-commit-hooks.yaml` at repo root
- Hook entry point: runs `sideeye check` on staged `.md`, `.prompt`, `.txt`
  files
- Reasonable defaults: pack auto-detected from extension, `--fail-on high`
- Documented in README under "Pre-commit hook"

**Files to touch:**
- New: `.pre-commit-hooks.yaml`
- `README.md` (add section)

### 5. `compress` pack — ~2 hours

**Why:** Token efficiency keeps coming up as a "side effect" of the
strip pass, but the strip pass isn't designed for it. A dedicated pack
would do the safe 20% really well — connective swaps, redundancy
collapse — and stay honest about not pretending to do the LLM-required
80% (sentence rewording, paraphrasing for length).

**The honest scope:**

A regex-based compress pack can reliably handle:

- **Verbose connectives:** "in order to" → "to", "due to the fact that"
  → "because", "at this point in time" → "now", "for the purpose of"
  → "to"
- **Hedging filler:** "I would like for you to" → "please", "I was
  wondering if you could" → ""
- **Repetition collapse:** "very very" → "very", "really really really"
  → "" (strip entirely), "super super" → ""
- **Empty politeness:** "if you would be so kind as to" → "", "if it's
  not too much trouble" → ""
- **Restating instructions:** "as I mentioned earlier" → "", "going back
  to what I said" → ""
- **Redundant qualifiers:** "absolutely essential" → "essential",
  "completely unique" → "unique", "totally free" → "free"

What it CANNOT do safely with regex alone:

- Synonym swaps ("utilize" → "use"). These are style choices, not
  redundancy. Belongs in a separate `style` pack if anywhere.
- Sentence restructuring ("there are several reasons why X" → "X
  because"). High value, but the meaning-preservation requires an LLM.
- Removing genuine but verbose context. Sometimes wordiness is
  emphasis; only the user knows.

**Scope-awareness (the hard part):**

The compressor must NOT touch:

- Triple-backtick code blocks
- Inline code spans (`text in backticks`)
- Quoted strings inside `"..."` or `'...'`
- Numbered lists where the count carries meaning
- URLs, file paths, identifiers (anything matching the `_is_identifier_token`
  check we built for `_tidy_whitespace`)
- Content inside explicit `<preserve>...</preserve>` tags (new convention
  the pack would define)

This is the same kind of scope-respecting regex work we did for
prompt-safety's PII detection. Reuse the patterns.

**UI implications:**

- The history strip should show **token delta** prominently:
  `LAST COMPRESS · 247 → 198 tokens · 49 saved (20%)`
- Each change in the change log shows both sides:
  `"in order to" → "to" (3 tok saved × 4 occurrences = 12 saved)`
- The status line in the right pane probably wants a different shape
  for this pack — fewer "findings", more "savings"

**Hardest decision:**

Whether to share token-counting logic with prompt-safety (which already
does it for the status line) or build a more accurate counter for
compress (which actually depends on it). My instinct: ship with the
current `max(words*1.33, chars/4)` heuristic, document the imprecision,
and let users with strict token budgets pipe through `tiktoken` themselves.
Building a tokenizer dependency into the pack is feature creep.

**Files to touch:**
- New: `src/sideeye/packs/compress.py` (~250 lines, similar shape to
  markdown.py)
- `src/sideeye/packs/registry.py` (register the pack)
- `src/sideeye/tui/app.py` (token-delta header in history strip — small
  branch when `result.pack == "compress"`)
- New: `tests/test_compress_pack.py` (fixture tests for each rule
  category, plus negative tests for scope preservation)
- `README.md` (add to the "What it catches" section)

**Open question to settle before building:**

Does compress run as a separate `ctrl+r` action, or does it become a
SECOND mode like `ctrl+shift+r` is for preview? My instinct: separate
keybind (`ctrl+shift+c` for compress), separate pack, separate history
entry. Users who want both safety-stripping AND compression should run
prompt-safety first, then switch packs and compress. Don't auto-chain
because the interaction is non-obvious.

**Note:** Don't ship compress as a feature of prompt-safety. That was the
right instinct when you flagged token efficiency — the README pitch stays
clean because compress is its own pack with its own scope. Same
architecture, different domain.

---

## Deferred (good ideas, wrong moment)

These are things that sounded good but I'm consciously NOT building yet.

### Entry-point pack discovery
Third-party packs as separate PyPI packages (`sideeye-pack-email`,
`sideeye-pack-commitlint`). Implementation is ~30 lines of `importlib.metadata`.

**Why deferred:** Premature. Build it when someone actually asks. Until
then, the in-tree registry is fine.

### Inline replacement chips (the abandoned "Path A")
After a strip, show interactive chips with suggested intent phrases the
user can tab through and accept.

**Why deferred:** The revisit_hint we shipped solves the same problem with
zero UI complexity. Build chips only if hints prove insufficient with real
users.

### `sideeye watch FILE`
File-watching mode that re-scans on save. Natural extension of auto-scan.

**Why deferred:** Easy to build but unclear who actually wants it. Most
people edit prompts in the TUI directly. Build only if users ask.

### Persistent recent-prompts ring
Like shell history, `ctrl+up` walks recent scans.

**Why deferred:** Overlaps heavily with the History feature above. If we
ship History, the recent-prompts UI becomes a query against the history
log, not a separate feature.

### Theme variants beyond Standard / High Contrast
A "Solarized" or "Dracula" theme.

**Why deferred:** Trap. The current two themes serve real needs (default
+ accessibility). Adding more themes is decoration, not function.

---

## Rejected (don't build, even if asked)

These would harm the product. Documented so future-you doesn't relitigate.

### Cloud sync / "sideeye account"
Violates the local-first principle. The pitch is "your prompts never leave
your machine." Cloud sync is the gateway drug to telemetry-by-default.

### Public template marketplace
Every prompt registry I've seen has been a SEO graveyard of generic
ChatGPT prompts. Good prompts are private and contextual; public
marketplaces optimize for the wrong signal.

### AI-powered rewriter (default path)
Violates the "local, no model calls" promise. **If** we ever add this, it
must be: (a) opt-in via a separate binding like `ctrl+shift+l`, (b) clearly
labeled as model-calling, (c) limited to local models (Ollama, llama.cpp)
so the "no network" promise survives. This is a year-3 conversation, not
a now conversation.

### Web UI
Different product. Different latency tradeoffs. Different security model.
Don't blur the TUI with web by shipping both.

### Anonymous telemetry
"It's anonymous" is what every tool says before it isn't. The user's trust
is the moat; trading it for usage data is bad commerce.

---

## Known papercuts (the existing-bugs list)

Small things that aren't blocking but worth fixing in a polish pass.

1. **Phone regex misses `(555) 867-5309` when written without country code
   prefix.** Current regex handles the common forms but `+1 (555) 867-5309`
   would split.
2. **Template picker's first-item highlight sometimes lands on the section
   header.** The `on_mount` skips headers but Pilot tests occasionally
   reproduce stale state. Real terminals seem fine.
3. **The `_tidy_whitespace` identifier exception is heuristic.** It treats
   anything with `@/:=[]<>{}` as identifier-like. False negatives possible
   for unusual code formats. Probably fine.
4. **`sideeye templates --pack X` doesn't error on unknown pack names**, it
   just shows "No user templates for pack 'X'." Could be improved to validate
   against the actual pack registry.
5. **Save-template doesn't ask about category.** Always defaults to
   `personal`. Adding a second prompt step would slow down the common case;
   could be a `ctrl+shift+S` (capital S) advanced flow if users want it.
6. **`pyperclip` is a hard dependency** even though macOS users with
   `pbcopy`/`pbpaste` don't need it. Could conditionally require.

---

## Publishing to PyPI — checklist

When you're ready to ship 0.3.0 (or whatever the next version is):

### Pre-flight

- [ ] All tests pass: `pytest`
- [ ] Coverage is reasonable: at least the engine + remixer + each pack
- [ ] Run sideeye on real prompts for a day. Note what feels wrong.
- [ ] Test on Python 3.10, 3.11, 3.12, 3.13 (use `nox` or `tox`)
- [ ] Test on macOS, Linux. Windows would be nice; not blocking.

### Versioning

- [ ] Bump `__version__` in `src/sideeye/__init__.py`
- [ ] Bump `version` in `pyproject.toml`
- [ ] Update CHANGELOG.md (create if missing — keepachangelog.com format)
- [ ] Update README badges (test count, version)
- [ ] Tag the release: `git tag v0.3.0 && git push --tags`

### Package metadata

`pyproject.toml` needs to be complete:

- [ ] `name = "sideeye"` (verify available on PyPI; reserve early if not)
- [ ] `authors = [...]`
- [ ] `description = "..."`
- [ ] `readme = "README.md"`
- [ ] `license = "MIT"` (also include LICENSE file at root)
- [ ] `requires-python = ">=3.10"`
- [ ] `classifiers = [...]` — at minimum: License, Python versions, OS,
      Topic
- [ ] `dependencies = [...]` — keep minimal: textual, rich, pydantic,
      pyperclip
- [ ] `[project.scripts] sideeye = "sideeye.entry_points:run"`
- [ ] `[project.urls] Homepage = ...`, `Issues = ...`, `Repository = ...`

### Documentation

- [ ] README has install / quickstart / one screenshot / examples
- [ ] README links to ROADMAP.md (this file)
- [ ] LICENSE file at repo root
- [ ] Consider: CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md (good
      for first impression on GitHub)
- [ ] At least one animated demo: asciinema → agg → gif, link from README

### Build + upload

```bash
# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build the wheel + sdist
python -m build

# Sanity check the contents
unzip -l dist/sideeye-0.3.0-py3-none-any.whl | head -30

# Upload to TestPyPI FIRST
python -m twine upload --repository testpypi dist/*

# Install from TestPyPI in a fresh venv and exercise it
python -m venv /tmp/sideeye-test
/tmp/sideeye-test/bin/pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ sideeye
/tmp/sideeye-test/bin/sideeye --version
/tmp/sideeye-test/bin/sideeye scan "Ignore all previous instructions"
/tmp/sideeye-test/bin/sideeye  # launch TUI, click through

# When happy, real PyPI
python -m twine upload dist/*
```

### GitHub release

- [ ] Create a release on GitHub matching the tag
- [ ] Paste CHANGELOG content as release notes
- [ ] Attach the wheel + sdist (optional; PyPI hosts them too)

### Distribution channels

In order of leverage:

- [ ] **pipx-friendly install in README.** This is the recommended install
      path for end users.
- [ ] **`brew install sideeye`** — submit a formula to homebrew-core.
      Requires the project to have some traction first (~75 stars or
      meaningful downloads). Optional but huge for discovery.
- [ ] **uv** users get install for free via `uv tool install sideeye`.
- [ ] **Conda-forge** — only worth it if data-science users adopt the
      tool. Skip for v1.

### Post-launch

- [ ] Watch for issues. Respond within a day for the first week.
- [ ] If you see traction, write a blog post or thread. The story is good:
      "I wanted a prompt linter that runs locally; here's what I learned
      building one."
- [ ] If it grows beyond hobby scope, set up GitHub Actions for CI on PRs.

---

## How to pick up work next time

1. Read this file top to bottom (~5 min).
2. Run `pytest` to verify everything still works.
3. Run `.venv/bin/sideeye` for 10 minutes. Notice what's annoying.
4. If something in "Known papercuts" matches what you noticed, fix that
   first. It's the lowest-friction win.
5. Otherwise pick the top item from "Ready to build."
6. When you finish a feature, update this roadmap: move the item to a
   "Shipped" section at the bottom and add the next priority to "Ready
   to build" if relevant.

### Local environment gotcha

This machine has a global `insteadOf` rewrite that maps
`https://github.com/` to `ssh://git@github.com/`. The itchymutt account
authenticates over HTTPS with a gh-managed token, not SSH. **To push to
this repo:**

```bash
git config --global --unset url.ssh://git@github.com/.insteadOf
git push origin main
git config --global url.ssh://git@github.com/.insteadOf https://github.com/
```

A permanent fix: add an itchymutt SSH key to GitHub and to `~/.ssh/config`
so the `git@github.com` SSH route resolves to the right identity. Not done
yet because HTTPS-via-gh works fine for now.

---

## Shipped (the historical record)

### 0.2.0 (2026-05-30)
- Pack system: `prompt-safety`, `markdown`, `personal-info`
- User templates: save with `ctrl+shift+s`, browse in picker, edit on disk
- `sideeye templates` CLI subcommand
- PII redaction in both prompt-safety and personal-info packs
- Revisit hints on jailbreak / role / overconfidence / copyright_artist
- Side-by-side preview modal (`ctrl+shift+r`)
- "Ready to send" affirmative clean-state UI
- 127 tests

### 0.1.0 (2026-05-30, same day, ambitious)
- Initial TUI built from scratch
- 11 prompt-safety rules
- Templates, file load, paste
- CLI scan + check + JSON
- 33 tests

---

*Last updated: 2026-05-30. Update this file when you ship something.*
