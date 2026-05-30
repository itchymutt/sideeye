# Changelog

Notable changes only. Full history is in git.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] — 2026-05-30

Initial public release.

### What's in

- **Three rule packs.** `prompt-safety` (default), `markdown`, `personal-info`. Adding your own is a single Python file.
- **PII redaction.** Emails, AWS / GitHub / GitLab / Hugging Face / Google / Stripe keys, and phone numbers get replaced with `[REDACTED:<kind>]` placeholders on `ctrl+r`.
- **`personal-info` pack.** User-configured sensitive strings from `~/.config/sideeye/personal.toml`. The categories you define become finding labels.
- **User templates.** Save the current editor as a markdown template with `ctrl+shift+s`. Templates live at `~/.config/sideeye/templates/<pack>/<slug>.md` and can be edited in any editor.
- **In-place safer rewrite.** `ctrl+r` strips known-risky phrases and redacts PII directly in the editor. `ctrl+z` undoes. `ctrl+y` copies.
- **Side-by-side preview.** `ctrl+shift+r` shows the proposed rewrite next to the original before applying.
- **Revisit hints.** When the rewriter strips a translatable shortcut (jailbreaks, totalizing roles, "make it perfect", named-artist style), the change log adds a quiet question pointing at what you might have actually meant.
- **CLI.** `sideeye`, `scan`, `check`, `packs`, `templates`. JSON output for tooling. Exit codes for CI gates.

### What's not

- No network calls. No model calls. No telemetry.
- The rewriter doesn't substitute pre-baked replacement phrases or prepend guardrail boilerplate. It removes risk; it doesn't ghostwrite intent.

---

[0.2.0]: https://github.com/itchymutt/sideeye/releases/tag/v0.2.0
