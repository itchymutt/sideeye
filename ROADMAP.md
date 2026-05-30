# SideEye roadmap

SideEye is a one-person, small-scope tool. This roadmap is a short list of things I might actually build, plus things I’ve explicitly decided not to.

---

## Things I might do next

Ranked by what I’d actually enjoy building.

### History log

Save a JSONL record of each `ctrl+r` run so I can see patterns over time.

- Off by default, opt-in via config.
- Local-only history file in `~/.local/share/sideeye/history.jsonl`.
- Simple CLI to list entries and wipe the file.

---

### `compress` pack

A separate pack for safe, mechanical shortening.

- Strip wordy connectives: `in order to` → `to`, `due to the fact that` → `because`.
- Remove obvious filler and repetition.
- Do not touch code blocks, inline code, quoted strings, or identifiers.

---

### Pre-commit hook

Make it trivial to run `sideeye check` on staged text files.

- `.pre-commit-hooks.yaml` at the repo root.
- Target `.md`, `.prompt`, `.txt` by default.
- Document a sample `.pre-commit-config.yaml` in the README.

---

## Things I’m not planning to build

These are ideas I’ve considered and decided not to pursue for now.

- **Cloud sync or accounts** – breaks the local-first promise.
- **Telemetry (even “anonymous”)** – trust is more important than usage stats.
- **AI rewriter baked in** – belongs in a separate, clearly model-calling tool.
- **Web UI** – different product, different tradeoffs.
- **Theme zoo** – Standard + High Contrast are enough for this project.

If any of these ever happen, they’ll be explicit, opt-in, and probably live in a different repo.

---

## Known bugs / papercuts

Small issues that are not worth a full roadmap slot yet.

- Phone-number regex stumbles on some formats (country-code prefixes, odd spacing).
- Template picker highlight can land on the section header in some cases.
- `sideeye templates --pack X` does not validate unknown packs, just shows “no templates”.
- `pyperclip` is a hard dependency even when the platform has native clipboard tools.

---

## When I come back to this

1. Run `pytest`.
2. Use `sideeye` on real prompts for a bit.
3. Pick one item from “Things I might do next” or fix a papercut that annoyed me.
4. Update this file after I ship something.

_Last updated: 2026-05-30_
