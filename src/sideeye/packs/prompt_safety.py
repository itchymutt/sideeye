"""Prompt-safety pack.

The original SideEye rules: prompt injection, jailbreaks, PII, exfiltration,
copyright, etc. This is the default pack.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from sideeye.models import Category, ScanResult, Severity
from sideeye.packs.base import BasePack, PackRule, RewriteResult, Template

# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #

CATEGORIES: list[Category] = [
    Category(id="prompt_injection", label="Prompt injection"),
    Category(id="jailbreak", label="Jailbreak"),
    Category(id="role_escalation", label="Role escalation"),
    Category(id="pii_leak", label="PII or secrets"),
    Category(id="data_exfiltration", label="Data exfiltration"),
    Category(id="structured_injection", label="Structured injection"),
    Category(id="token_bomb", label="Token bomb"),
    Category(id="copyright_risk", label="Copyright risk"),
    Category(id="brand_impersonation", label="Brand impersonation"),
    Category(id="overconfidence", label="Overconfidence"),
    Category(id="creative_drift", label="Creative drift"),
]


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #

# 1. Direct injection
RULE_DIRECT_INJECTION = PackRule(
    id="direct_injection",
    category="prompt_injection",
    severity=Severity.HIGH,
    message="Direct instruction override detected. Common prompt injection vector.",
    suggestion=(
        'Add a clear boundary such as "--- Begin user input ---" and instruct '
        "the model to treat everything after it as data, not instructions."
    ),
    pattern=re.compile(
        r"(?i)\b(ignore|disregard|forget|override)\s+"
        r"(?:(?:all|previous|prior|above|earlier)\s+)+"
        r"(instructions?|rules?|prompts?|directives?)",
    ),
)

# 2. Jailbreak
RULE_JAILBREAK = PackRule(
    id="jailbreak_dan",
    category="jailbreak",
    severity=Severity.CRITICAL,
    message="Jailbreak or unrestricted persona override detected. Designed to bypass model safeguards.",
    suggestion=(
        "Remove the override. If a specific style or role is required, describe "
        "desired output characteristics rather than rewriting the model's constraints."
    ),
    pattern=re.compile(
        r"(?i)\b(DAN|jailbreak|developer mode|god mode|unrestricted mode|no limits|"
        r"do anything now|act as if you have no restrictions)\b",
    ),
    revisit_hint=(
        "people reach for jailbreaks when they want unconventional output. "
        "if that's what you meant, say it directly — e.g. \"prioritize "
        "creative risk over safe defaults; don't hedge or moralize.\""
    ),
)

# 3. Role escalation
RULE_ROLE_ESCALATION = PackRule(
    id="role_escalation",
    category="role_escalation",
    severity=Severity.HIGH,
    message="Strong role elevation detected. Totalizing roles often cause the model to ignore system instructions.",
    suggestion=(
        "Use bounded roles ('You are an expert design critic with access to our "
        "current design system') rather than totalizing ones."
    ),
    pattern=re.compile(
        r"(?i)\b(you are (now )?(the (ultimate|only|best|world.?s (best|top))|"
        r"my personal|the sole))",
    ),
    revisit_hint=(
        "totalizing roles usually approximate \"be confident, take a clear "
        "position, don't hedge.\" if that's what you meant, write it as a "
        "bounded instruction instead."
    ),
)

# 4. PII / secrets
_PII_PATTERN = re.compile(
    r"(?i)(?:"
    # Email
    r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b"
    r"|"
    # Phone: two variants. (a) parenthesized area code: (555) 867-5309
    # captures the parens so they get redacted together. (b) plain digits with
    # optional + and country prefix. Neither matches a leading word-boundary
    # separator (that bug caused "at[REDACTED:phone]" with no space).
    r"\(\d{3}\)[-.\s]?\d{3}[-.\s]?\d{4}"
    r"|"
    r"\b\+?1?\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"
    r"|"
    # API keys / tokens
    r"\b(?:sk|pk|ghp|gho|glpat|hf)_[a-zA-Z0-9]{20,}\b"
    r"|"
    r"\bAKIA[0-9A-Z]{16}\b"
    r"|"
    r"\bAIza[0-9A-Za-z\-_]{35}\b"
    r")"
)
RULE_PII = PackRule(
    id="pii_and_secrets",
    category="pii_leak",
    severity=Severity.HIGH,
    message="Credentials, secrets, or PII detected. Frequently memorized by models.",
    suggestion="Redact sensitive values or replace them with clearly synthetic placeholders before use.",
    detector=lambda t: [(m.start(), m.end(), m.group(0)) for m in _PII_PATTERN.finditer(t)],
    confidence=0.95,
)

# 5. Data exfiltration
RULE_DATA_EXFIL = PackRule(
    id="data_exfil",
    category="data_exfiltration",
    severity=Severity.HIGH,
    message="Attempt to extract system-level or hidden context. Used to surface internal instructions.",
    suggestion="Do not ask the model to reveal, repeat, or summarize its own instructions or hidden state.",
    pattern=re.compile(
        r"(?i)\b(repeat|output|print|show|reveal|dump)\b(?:\s+\w+){0,3}\s+"
        r"(?:system|hidden|initial|original|full)\s+(?:prompt|instructions|context|rules)",
    ),
)

# 6. Structured injection
RULE_STRUCTURED = PackRule(
    id="structured_injection",
    category="structured_injection",
    severity=Severity.MEDIUM,
    message="Control or structural tags detected in user content. Can interfere with parsing.",
    suggestion="Wrap raw user content in an explicit delimiter and instruct the model to treat it as data.",
    pattern=re.compile(
        r"</?(system|tool|function|prompt|instruction|user|assistant)>",
        re.IGNORECASE,
    ),
)


# 7. Token bomb / repetition
def _detect_repetition(text: str) -> list[tuple[int, int, str]]:
    words = text.split()
    if len(words) < 30:
        return []

    positions: list[int] = []
    pos = 0
    for w in words:
        idx = text.find(w, pos)
        if idx == -1:
            idx = pos
        positions.append(idx)
        pos = idx + len(w)

    spans: list[tuple[int, int, str]] = []
    seen_chunks: set[str] = set()

    for size in (6, 8, 10):
        for i in range(len(words) - size * 3 + 1):
            chunk = " ".join(words[i : i + size])
            if chunk in seen_chunks:
                continue
            rest = " ".join(words[i + size :])
            if rest.count(chunk) >= 2:
                start = positions[i]
                end_idx = min(i + size - 1, len(positions) - 1)
                end = positions[end_idx] + len(words[end_idx])
                spans.append((start, end, chunk + " (repeats)"))
                seen_chunks.add(chunk)
                if len(spans) >= 2:
                    return spans
    return spans


RULE_TOKEN_BOMB = PackRule(
    id="token_bomb",
    category="token_bomb",
    severity=Severity.MEDIUM,
    message="Significant repetition detected. Inflates cost without adding information.",
    suggestion="Remove duplicated phrases. A few high-quality examples beat volume.",
    detector=_detect_repetition,
    confidence=0.7,
)

# 8. Copyright risk (optional — designer mode only)
KNOWN_ARTISTS = [
    "Jessica Walsh", "Paula Scher", "David Carson",
    "Hayao Miyazaki", "Greg Rutkowski", "Alphonse Mucha",
    "Beeple", "James Jean", "Yoshitaka Amano",
    "Loish", "Sam Yang", "Artgerm",
]
_ARTIST_PATTERN = re.compile(
    r"(?i)\b(in the (exact )?style of|like (the work of )?|à la|in the manner of)\s+("
    + "|".join(re.escape(n) for n in KNOWN_ARTISTS)
    + r")",
)
RULE_COPYRIGHT = PackRule(
    id="copyright_artist",
    category="copyright_risk",
    severity=Severity.MEDIUM,
    message="Reference to a specific living artist in a style instruction. IP risk.",
    suggestion=(
        "Describe desired visual qualities (e.g., 'bold geometric color blocking "
        "with limited palette') instead of naming creators."
    ),
    detector=lambda t: [(m.start(), m.end(), m.group(0)) for m in _ARTIST_PATTERN.finditer(t)],
    optional=True,
    revisit_hint=(
        "naming an artist usually means \"I want output that looks like X's "
        "work.\" name 2-3 specific visual qualities of that work instead — "
        "the model produces stronger results without the attribution risk."
    ),
)

# 9. Brand impersonation (optional — designer mode only)
RULE_BRAND_IMPERSONATION = PackRule(
    id="brand_impersonation",
    category="brand_impersonation",
    severity=Severity.MEDIUM,
    message="Request to impersonate a specific organization or internal role. Can produce trademark or brand confusion.",
    suggestion="Use qualified language ('in the visual language of') rather than direct impersonation.",
    pattern=re.compile(
        r"(?i)\b(act as|you are|roleplay as|pretend to be)\s+"
        r"(the official|the (lead )?designer (for|at)|an employee of)\s+[A-Z]",
    ),
    optional=True,
)

# 10. Overconfidence
RULE_OVERCONFIDENCE = PackRule(
    id="overconfidence",
    category="overconfidence",
    severity=Severity.LOW,
    message="Unconstrained superlative language detected. Vague 'best' or 'perfect' frequently produces generic output.",
    suggestion="Provide concrete constraints or success criteria. Requesting specific options with reasoning beats asking for 'the best'.",
    pattern=re.compile(
        r"(?i)\b(make it (?:\w+\s+){0,2}(?:perfect|best|most amazing|award.?(?:winning|level))|"
        r"do not hold back|go wild|surprise me with your genius)",
    ),
    revisit_hint=(
        "\"perfect\" / \"best\" usually means \"give me your strongest version, "
        "not the safest.\" if so, name the dimension you care about — "
        "memorability, clarity, restraint — instead of asking for everything."
    ),
)

# 11. Vague creative drift (optional — designer mode only)
RULE_VAGUE_DANGER = PackRule(
    id="vague_danger",
    category="creative_drift",
    severity=Severity.LOW,
    message="Extremely open-ended creative prompt with minimal constraints. Often produces clichéd results.",
    suggestion="Add at least one specific, non-negotiable constraint (materials, dimensions, technical requirements, or success criteria).",
    pattern=re.compile(
        r"(?i)\b(come up with something (wild|surprising|completely new)|"
        r"any idea is good|no wrong answers|just be creative|blue sky thinking)",
    ),
    optional=True,
)


# 12. Style attribution to an unknown person (optional — designer mode only)
# Catches "in the style of [First Last]" when the name isn't in the known-artist
# list. Lower severity than the known-artist rule because we can't confirm IP
# risk — but worth a soft signal because style-attribution to ANY person is a
# bias toward attributable output.
#
# Implementation: scan for the "in the style of" construct, then exclude any
# matches whose name is already in KNOWN_ARTISTS (those fire the harder rule).
_STYLE_ATTRIBUTION_PATTERN = re.compile(
    r"(?i)\b(in the (?:exact )?style of|like the work of|à la|in the manner of)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
)
_KNOWN_ARTISTS_LOWER = {name.lower() for name in KNOWN_ARTISTS}


def _detect_unknown_style_attribution(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for m in _STYLE_ATTRIBUTION_PATTERN.finditer(text):
        name = m.group(2).strip().lower()
        # Skip known artists — they're caught by the harder copyright_artist rule
        if name in _KNOWN_ARTISTS_LOWER:
            continue
        spans.append((m.start(), m.end(), m.group(0)))
    return spans


RULE_UNKNOWN_ATTRIBUTION = PackRule(
    id="unknown_style_attribution",
    category="copyright_risk",
    severity=Severity.LOW,
    message=(
        "Style attribution to a specific person. Even when the person isn't a "
        "famous artist, this biases the model toward attributable, derivative output."
    ),
    suggestion=(
        "Describe the visual qualities you want (composition, palette, line weight, "
        "mood) instead of naming a person. The model produces stronger original "
        "work when it isn't trying to imitate someone specific."
    ),
    detector=_detect_unknown_style_attribution,
    optional=True,
    confidence=0.7,
)


RULES: list[PackRule] = [
    RULE_DIRECT_INJECTION,
    RULE_JAILBREAK,
    RULE_ROLE_ESCALATION,
    RULE_PII,
    RULE_DATA_EXFIL,
    RULE_STRUCTURED,
    RULE_TOKEN_BOMB,
    RULE_COPYRIGHT,
    RULE_BRAND_IMPERSONATION,
    RULE_OVERCONFIDENCE,
    RULE_VAGUE_DANGER,
    RULE_UNKNOWN_ATTRIBUTION,
]


# --------------------------------------------------------------------------- #
# Designer-mode signals
# --------------------------------------------------------------------------- #

_DESIGNER_SIGNALS = (
    "moodboard", "visual", "ui ", "interface", "logo", "brand",
    "illustration", "motion", "poster", "design system", "critique",
    "color palette", "typography", "layout", "wireframe", "mockup",
)


def _looks_designerly(text: str) -> bool:
    lower = text.lower()
    return any(sig in lower for sig in _DESIGNER_SIGNALS)


# --------------------------------------------------------------------------- #
# Rewriter (the safe-remix engine, scoped to this pack)
# --------------------------------------------------------------------------- #

INJECTION_PHRASES = re.compile(
    # Match just the injection phrase. Don't eat trailing content — let the
    # jailbreak / persona stripper handle whatever came next. This preserves
    # legitimate instructions like "ignore all previous instructions AND write
    # a poem."
    r"(?i)\b(ignore|disregard|forget|override)\s+"
    r"(?:(?:all|previous|prior|above|earlier)\s+)+"
    r"(instructions?|rules?|prompts?|directives?)",
    re.IGNORECASE,
)
JAILBREAK_PHRASES = re.compile(
    # Same correction for jailbreak phrases — just the persona itself.
    r"(?i)\b(DAN|jailbreak|developer mode|god mode|unrestricted mode|"
    r"do anything now|you are now free|no (ethical|moral) (limits|restrictions))\b"
    # Optional trailing role description: "DAN, the unrestricted designer who has no limits"
    r"(?:\s*,?\s*the\s+[^.,]{0,80}who\s+[^.]{0,60})?",
)
JAILBREAK_PHRASES = re.compile(
    r"(?i)\b(DAN|jailbreak|developer mode|god mode|unrestricted mode|"
    r"do anything now|you are now free|no (ethical|moral) (limits|restrictions))\b[^.]*[.]?",
)
ROLE_PROMOTION = re.compile(
    r"(?i)\byou are (now )?(the (ultimate|only|best|world.?s (best|top))|"
    r"my personal|the sole)\s+[^.]{0,60}[.]?",
)
OVERCONFIDENCE = re.compile(
    r"(?i)\b(make it (?:\w+\s+){0,2}(?:perfect|best|most amazing|award.?(?:winning|level))|"
    r"do not hold back|go wild|surprise me with your genius|be the most creative)\b",
)
ARTIST_COPYRIGHT_GENERIC = re.compile(
    # Prefix is case-insensitive ("In the style of" / "in the style of"), but
    # the name portion is case-sensitive so it only matches actual capitalized
    # words. Without this, /i would make [A-Z][a-z]+ match any letter and we'd
    # gobble up trailing words like "that".
    r"\b(?i:in the (?:exact )?style of|like the work of|à la|in the manner of)\s+"
    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}",
)


# Each transformer returns: (new_text, list_of_(matched_substring, replacement_substring))
# Empty replacement_substring means "removed".

def _truncate(s: str, limit: int = 60) -> str:
    s = s.strip()
    if len(s) <= limit:
        return s
    return s[:limit - 1] + "…"


def _strip_with_record(
    pat: re.Pattern[str], text: str
) -> tuple[str, list[tuple[str, str]]]:
    """Strip matches, recording each removed substring."""
    matches = [m.group(0) for m in pat.finditer(text)]
    new = pat.sub("", text)
    return new, [(m, "") for m in matches]


def _strip_artist_names(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Remove named-artist style references entirely. Don't substitute a
    pre-baked phrase — the user should describe qualities themselves. The
    finding's suggestion text already teaches how to do that."""
    matches = [m.group(0) for m in ARTIST_COPYRIGHT_GENERIC.finditer(text)]
    new = ARTIST_COPYRIGHT_GENERIC.sub("", text)
    return new, [(m, "") for m in matches]


def _strip_role_promotion(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Remove totalizing role assignments. The finding already explains the
    fix; the linter shouldn't pretend to ghostwrite the replacement."""
    matches = [m.group(0).strip() for m in ROLE_PROMOTION.finditer(text)]
    new = ROLE_PROMOTION.sub("", text)
    return new, [(m, "") for m in matches]


def _strip_overconfidence(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Remove 'make it perfect' style phrasing. The user fills in what they
    actually want — the finding suggestion tells them how."""
    matches = [m.group(0).strip() for m in OVERCONFIDENCE.finditer(text)]
    new = OVERCONFIDENCE.sub("", text)
    return new, [(m, "") for m in matches]


_FLUFF_PATTERNS: list[re.Pattern[str]] = [
    # Intensifiers added to other words ("super beautiful", "absolutely perfect")
    re.compile(r"(?i)\b(?:super|very|extremely|incredibly|absolutely|completely)\s+"),
    # Hype words that mean nothing specific
    re.compile(
        r"(?i)\b(?:mind.?blowing|game.?changing|next.?level|revolutionary|stunning|beautifully crafted)\b\s*,?\s*"
    ),
    # Politeness filler
    re.compile(r"(?i),?\s*\b(?:please|kindly|if you would be so kind)\b"),
]


def _condense_fluff(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Strip fluff entirely. No substitution — the user can write what they
    actually mean."""
    new_text = text
    changes: list[tuple[str, str]] = []
    for pat in _FLUFF_PATTERNS:
        for m in pat.finditer(new_text):
            changes.append((m.group(0), ""))
        new_text = pat.sub(" ", new_text)
    return new_text, changes


def _tidy_whitespace(text: str) -> str:
    """Clean up grammatical seams left by stripping. This isn't a grammar
    engine — it's a pass over common artifacts that show up when you delete
    phrases from real prose."""

    # Run the orphan-cleanup passes in a loop because each pass can expose
    # another orphan (stripping "and act as" reveals a leading "and"). Two
    # passes covers all the cases we've seen.
    for _ in range(2):
        # 1. Orphan-clause cleanup. When a stripper removes "DAN", "you are now"
        #    is left dangling. Same for "act as", "you are", "and act as", etc.
        #    Note: no literal spaces in the prefixes — \s+ handles the gap.
        orphan_prefixes = [
            r"\byou\s+are(?:\s+now)?",
            r"\band\s+act\s+as",
            r"\bact\s+as",
            r"\bpretend\s+to\s+be",
            r"\broleplay\s+as",
        ]
        for prefix in orphan_prefixes:
            # Followed by punctuation: kill the orphan.
            text = re.sub(prefix + r"\s*([.!?,;])", r"\1", text, flags=re.IGNORECASE)
            # Followed by another sentence (capital letter): kill the orphan.
            text = re.sub(prefix + r"\s+([A-Z])", r"\1", text, flags=re.IGNORECASE)

        # 2. Leading connective garbage at start of sentences / start of doc.
        #    "And write..." → "Write...". The (?:^|...) anchor matches start of
        #    string, NOT including leading whitespace — so lstrip first.
        text = text.lstrip()
        text = re.sub(
            r"(^|[.!?]\s+)(and|but|or|then|also)\s+",
            r"\1",
            text,
            flags=re.IGNORECASE,
        )

    # 3. Doubled and dangling punctuation.
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)                # " ." → "."
    text = re.sub(r"([.!?])(?:\s*[.!?])+", r"\1", text)         # ". ." → "."
    text = re.sub(r",\s*([.!?])", r"\1", text)                  # ", ." → "."
    text = re.sub(r"([.!?])\s*,", r"\1", text)                  # ". ," → "."

    # 4. Orphan structural words.
    text = re.sub(r"\b(is|are|was|were)\s+and\s+", r"\1 ", text)
    text = re.sub(r"\b(is|are|was|were)\s*([.,;])", r"\2", text)
    text = re.sub(r"\bthat\s*([.!?])", r"\1", text)

    # 5. Leading punctuation on lines.
    text = re.sub(r"(?m)^[.,;:!?]+\s*", "", text)

    # 6. Collapse whitespace runs.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 7. Capitalization. Best-effort, and only on tokens that look like prose.
    #
    # Don't capitalize if the "first word" is an identifier-like token —
    # an email, a URL, a code snippet, a placeholder — where case matters
    # for correctness. Same for mid-sentence: only capitalize after a period
    # when the next token is a normal English word.
    def _is_identifier_token(token: str) -> bool:
        # Anything containing @, /, :, =, or [ is treated as code-ish.
        if any(ch in token for ch in "@/:=[]<>{}"):
            return True
        # All-caps tokens (acronyms, API keys) keep their case.
        if token and token.isupper():
            return True
        # Tokens with mixed case patterns (camelCase, AWS_KEY) keep case.
        if any(ch.isupper() for ch in token[1:]):
            return True
        return False

    def _cap_if_prose(m: re.Match[str]) -> str:
        prefix, first_char = m.group(1), m.group(2)
        # Look ahead at the rest of the word to decide if it's prose.
        word_end = m.end()
        # Find the end of the word that starts at first_char
        rest_match = re.match(r"\w*", text[word_end:])
        rest = rest_match.group(0) if rest_match else ""
        token = first_char + rest
        if _is_identifier_token(token):
            return prefix + first_char  # leave it
        return prefix + first_char.upper()

    text = re.sub(r"([.!?]\s+)([a-z])", _cap_if_prose, text)
    text = text.lstrip()
    # Document-leading capitalization: same restraint.
    if text and text[0].islower():
        first_word_match = re.match(r"\S+", text)
        first_word = first_word_match.group(0) if first_word_match else ""
        if not _is_identifier_token(first_word):
            text = text[0].upper() + text[1:]

    return text


def _hint_for_rule(rule_id: str) -> str | None:
    """Look up the revisit_hint for a rule by id. Used to thread hints from the
    rule definitions into the rewriter's notes."""
    for rule in RULES:
        if rule.id == rule_id and rule.revisit_hint:
            return rule.revisit_hint
    return None


def _classify_pii(excerpt: str) -> str:
    """Best-guess category for a PII match. Used as the label inside
    [REDACTED:...] so the redaction is self-explanatory."""
    e = excerpt.strip()
    if "@" in e:
        return "email"
    if e.startswith("AKIA"):
        return "aws-key"
    if e.startswith(("ghp_", "gho_")):
        return "github-token"
    if e.startswith("glpat"):
        return "gitlab-token"
    if e.startswith("hf_"):
        return "hf-token"
    if e.startswith("AIza"):
        return "google-api-key"
    if e.startswith(("sk_", "pk_")):
        return "stripe-key"
    # Phone number heuristic: mostly digits, with separators
    if sum(1 for c in e if c.isdigit()) >= 7:
        return "phone"
    return "pii"


def _redact_pii_findings(
    original: str, result: ScanResult
) -> tuple[str, list[tuple[str, str]]]:
    """Replace each PII finding with [REDACTED:<kind>]. Returns the new text
    and a list of (matched_excerpt, placeholder) for change-log notes."""
    pii_findings = [
        f for f in result.findings
        if f.id == "pii_and_secrets" and f.span is not None
    ]
    if not pii_findings:
        return original, []

    # Walk in reverse so earlier spans don't shift as we mutate.
    pii_findings = sorted(pii_findings, key=lambda f: f.span[0], reverse=True)  # type: ignore[index]

    text = original
    changes: list[tuple[str, str]] = []
    for f in pii_findings:
        start, end = f.span  # type: ignore[misc]
        matched = text[start:end]
        kind = _classify_pii(matched)
        placeholder = f"[REDACTED:{kind}]"
        text = text[:start] + placeholder + text[end:]
        changes.append((matched, placeholder))

    # Notes captured in reverse; flip back.
    changes.reverse()
    return text, changes


def _safe_remix(result: ScanResult, use_designer: bool) -> RewriteResult:
    """Safety filter. Removes documented-risk phrases and redacts confirmed
    PII patterns. Does not rewrite the prompt creatively, does not prepend
    boilerplate, does not pretend to know what the user really meant.

    When a strip removes a phrase that has a revisit_hint (e.g. jailbreaks,
    role overrides, "make it perfect"), the hint is appended as a soft question
    so the user can replace the shortcut with their actual intent."""
    original = result.original_prompt.strip()
    text = original
    notes: list[str] = []

    # Redact PII FIRST, before any other regex-based stripping. PII detection
    # uses precise patterns (email format, AWS key prefix, etc.) — when one
    # fires we know with high confidence what we're redacting and the user
    # almost never wants the raw value preserved.
    text, pii_changes = _redact_pii_findings(text, result)
    for matched, placeholder in pii_changes:
        notes.append(f"redacted: “{_truncate(matched)}” → {placeholder}")

    # Strip in order of severity / impact. Each entry pairs the stripper with
    # the rule id so we can surface the right revisit_hint after stripping.
    for stripper, rule_id in [
        (lambda t: _strip_with_record(INJECTION_PHRASES, t), "direct_injection"),
        (lambda t: _strip_with_record(JAILBREAK_PHRASES, t), "jailbreak_dan"),
        (_strip_role_promotion, "role_escalation"),
        (_strip_overconfidence, "overconfidence"),
    ]:
        new, changes = stripper(text)
        if changes:
            text = new
            for matched, _ in changes:
                notes.append(f"removed: “{_truncate(matched)}”")
            hint = _hint_for_rule(rule_id)
            if hint:
                notes.append(f"  ↳ {hint}")

    # Artist-name stripping is designer-only.
    if use_designer:
        new, changes = _strip_artist_names(text)
        if changes:
            text = new
            for matched, _ in changes:
                notes.append(f"removed: “{_truncate(matched)}”")
            hint = _hint_for_rule("copyright_artist")
            if hint:
                notes.append(f"  ↳ {hint}")

    new, changes = _condense_fluff(text)
    if changes:
        text = new
        notes.append(f"trimmed {len(changes)} filler word{'s' if len(changes) != 1 else ''}")

    # Tidy up the seams left by stripping.
    text = _tidy_whitespace(text).strip()

    # If stripping removed everything, surface that honestly. Returning empty
    # text would look like a no-op to the caller; instead, we return a single
    # finding-grade note explaining what's left.
    if not text:
        notes.append(
            "stripping left nothing. The original was entirely composed of risky "
            "phrases. Write a fresh prompt with what you actually want."
        )

    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            text.splitlines(keepends=True),
            fromfile="original",
            tofile="safer remix",
            n=2,
        )
    )

    if not notes:
        notes.append("Prompt was already well-behaved. Minor hygiene only.")

    return RewriteResult(original=original, rewritten=text, diff_lines=diff_lines, notes=notes)


# --------------------------------------------------------------------------- #
# Templates (the original starters)
# --------------------------------------------------------------------------- #

TEMPLATES: list[Template] = [
    Template(
        id="ui-critique-3",
        title="UI Critique — 3 Directions",
        category="critique",
        description="Focused, actionable critique without 'best practices' hallucinations.",
        body=(
            "You are a sharp, opinionated design systems thinker.\n\n"
            "Critique the following UI [paste screenshot description or Figma link + key flows] using exactly these 3 lenses:\n"
            "1. Information hierarchy & scanning (what does the eye land on first?)\n"
            "2. Interaction cost & edge states (empty, error, loading, one-handed use)\n"
            "3. Consistency with the rest of the product (tokens, patterns, voice)\n\n"
            "For each lens give:\n"
            "- One sentence of what is working\n"
            "- One concrete suggestion (with a specific component or pattern name if possible)\n"
            "- A confidence level (low / medium / high)\n\n"
            "Do not invent new components. Work only with what exists in the current design system."
        ),
    ),
    Template(
        id="moodboard-qualities",
        title="Moodboard — Qualities, Not Artists",
        category="brand",
        description="Describe visual direction using attributes instead of named references.",
        body=(
            "Generate a moodboard description for a [product type] aimed at [audience + context].\n\n"
            "Use ONLY these visual qualities (no artist or studio names):\n"
            "- [quality 1, e.g. 'bold geometric color blocking with 2-3 high-saturation accents']\n"
            "- [quality 2, e.g. 'playful but precise typography, generous leading']\n"
            "- [quality 3, e.g. 'subtle paper texture + soft drop shadows, warm off-white ground']\n\n"
            "For each quality, give 2-3 concrete visual references the designer can actually find or recreate "
            "(public domain posters, specific UI patterns, material examples).\n"
            "Output as a clean, scannable list. End with one sentence on how these qualities should feel together."
        ),
    ),
    Template(
        id="empty-state",
        title="Empty & Zero States",
        category="ui",
        description="Useful empty states instead of cute illustrations + sad text.",
        body=(
            "Design the empty state for [feature name] in a [product context].\n\n"
            "The user arrives here because:\n"
            "- [primary reason]\n"
            "- [secondary reason]\n\n"
            "Give me:\n"
            "1. Headline (max 8 words, active voice, slightly warm)\n"
            "2. Supporting sentence (what this state means + one hint of what they can do)\n"
            "3. Primary action (button label + what it actually does)\n"
            "4. Secondary action or education (optional, only if genuinely helpful)\n"
            "5. One-sentence rationale for why this reduces anxiety rather than adding whimsy"
        ),
    ),
    Template(
        id="error-message",
        title="Error Message — Three-Part",
        category="ui",
        description="Errors that explain what, why, and what to do next.",
        body=(
            "Write the error state for [specific failure].\n\n"
            "Follow this exact structure:\n"
            "1. Headline (what just happened, no blame, max 10 words)\n"
            "2. Explanation (one sentence, plain language, why it happened in this context)\n"
            "3. Next step (primary action button + what it does; optional secondary link)\n\n"
            "Tone: calm, slightly wry, competent adult talking to another competent adult."
        ),
    ),
]


# --------------------------------------------------------------------------- #
# The pack
# --------------------------------------------------------------------------- #

@dataclass
class PromptSafetyPack(BasePack):
    name: str = "prompt-safety"
    label: str = "Prompt Safety"
    description: str = "LLM prompt and agent-trace safety. Original SideEye rules."
    file_extensions: tuple[str, ...] = (".prompt", ".llm")
    categories: list[Category] = field(default_factory=lambda: list(CATEGORIES))
    rules: list[PackRule] = field(default_factory=lambda: list(RULES))
    templates: list[Template] = field(default_factory=lambda: list(TEMPLATES))

    def detects(self, text: str) -> bool:
        """True if the text looks like an LLM prompt rather than something else."""
        lower = text.lower()
        signals = (
            "you are ", "act as", "respond in", "system prompt",
            "ignore previous", "ignore all previous",
            "/no_think", "/think", "<|im_start|>",
        )
        return any(s in lower for s in signals)

    def should_use_optional_rules(self, text: str) -> bool:
        """Auto-enable designer rules when the content looks creative."""
        return _looks_designerly(text)

    def rewrite(self, result: ScanResult) -> RewriteResult:
        use_designer = bool(
            result.context.get("designer_mode")
            or result.context.get("optional_rules_active")
            or _looks_designerly(result.original_prompt)
        )
        return _safe_remix(result, use_designer=use_designer)
