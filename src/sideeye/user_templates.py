"""User-defined templates.

Templates the user saves from the TUI live as markdown files at:
    $XDG_CONFIG_HOME/sideeye/templates/<pack-name>/<slug>.md

A template is a markdown file. Optional YAML-style frontmatter at the top
provides metadata:

    ---
    title: My Daily Critique Prompt
    category: critique
    description: My personalized version of the design crit starter
    ---

    You are a senior product designer...

Frontmatter is optional. If absent:
- The first H1 (`# Title`) is the title
- Category defaults to "personal"
- Description is empty

Slugs are auto-derived from the title (lowercase, alphanumeric + hyphens).

The user can edit these files directly in any editor. Sideeye reads them
fresh every time the picker opens.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from sideeye.packs.base import Template

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

def templates_root() -> Path:
    """Where user templates live. Respects $XDG_CONFIG_HOME and the
    SIDEEYE_TEMPLATES_DIR override (used by tests).
    """
    override = os.environ.get("SIDEEYE_TEMPLATES_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "sideeye" / "templates"


def pack_templates_dir(pack_name: str) -> Path:
    return templates_root() / pack_name


# --------------------------------------------------------------------------- #
# Slug generation
# --------------------------------------------------------------------------- #

_SLUG_STRIP = re.compile(r"[^a-z0-9-]+")
_SLUG_COLLAPSE = re.compile(r"-{2,}")


def slugify(title: str) -> str:
    """Turn a free-form title into a filesystem-safe slug."""
    s = title.strip().lower()
    s = s.replace("_", "-").replace(" ", "-")
    s = _SLUG_STRIP.sub("-", s)
    s = _SLUG_COLLAPSE.sub("-", s)
    s = s.strip("-")
    return s or "untitled"


# --------------------------------------------------------------------------- #
# Frontmatter parsing
# --------------------------------------------------------------------------- #

_FRONTMATTER_PATTERN = re.compile(
    r"\A---\n(.*?)\n---\n+(.*)\Z",
    re.DOTALL,
)


@dataclass
class _Parsed:
    metadata: dict[str, str]
    body: str


def _parse_frontmatter(text: str) -> _Parsed:
    """Tiny YAML-frontmatter parser. We only support simple `key: value` lines.
    Real YAML would be overkill here — templates need title, category, and
    description, all strings."""
    m = _FRONTMATTER_PATTERN.match(text)
    if not m:
        return _Parsed(metadata={}, body=text)

    raw_meta = m.group(1)
    body = m.group(2)
    metadata: dict[str, str] = {}
    for line in raw_meta.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        # Strip surrounding quotes if present.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        metadata[key.strip().lower()] = value
    return _Parsed(metadata=metadata, body=body)


_H1_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _title_from_body(body: str, fallback: str) -> str:
    """Find the first H1 in the body, else use the fallback."""
    m = _H1_PATTERN.search(body)
    if m:
        return m.group(1).strip()
    return fallback


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def load_user_templates(pack_name: str) -> list[Template]:
    """Read every .md file in the pack's user templates dir.

    Returns a list of Template objects, sorted by modification time descending
    (most-recently-edited first). Silently skips files with read errors.
    """
    pack_dir = pack_templates_dir(pack_name)
    if not pack_dir.exists() or not pack_dir.is_dir():
        return []

    templates: list[tuple[float, Template]] = []
    for path in pack_dir.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parsed = _parse_frontmatter(text)
        fallback_title = path.stem.replace("-", " ").title()
        title = parsed.metadata.get("title") or _title_from_body(parsed.body, fallback_title)
        category = parsed.metadata.get("category", "personal")
        description = parsed.metadata.get("description", "")
        tpl = Template(
            id=f"user:{path.stem}",
            title=title,
            category=category,
            description=description,
            body=parsed.body.strip(),
        )
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0
        templates.append((mtime, tpl))

    templates.sort(key=lambda pair: pair[0], reverse=True)
    return [tpl for _, tpl in templates]


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #

@dataclass
class SaveResult:
    path: Path
    title: str
    overwrote: bool


def save_user_template(
    pack_name: str,
    title: str,
    body: str,
    *,
    category: str = "personal",
    description: str = "",
    overwrite: bool = False,
) -> SaveResult:
    """Write a user template to disk.

    Returns a SaveResult with the final path and whether an existing file was
    overwritten. Raises FileExistsError if the file exists and overwrite=False.
    """
    title = title.strip()
    if not title:
        raise ValueError("title must not be empty")
    if not body.strip():
        raise ValueError("body must not be empty")

    pack_dir = pack_templates_dir(pack_name)
    pack_dir.mkdir(parents=True, exist_ok=True)

    slug = slugify(title)
    path = pack_dir / f"{slug}.md"

    overwrote = path.exists()
    if overwrote and not overwrite:
        raise FileExistsError(str(path))

    # Build the file content with frontmatter when category or description add info.
    frontmatter_lines = [f"title: {title}"]
    if category and category != "personal":
        frontmatter_lines.append(f"category: {category}")
    if description:
        frontmatter_lines.append(f"description: {description}")

    content = "---\n" + "\n".join(frontmatter_lines) + "\n---\n\n" + body.strip() + "\n"
    path.write_text(content, encoding="utf-8")

    return SaveResult(path=path, title=title, overwrote=overwrote)


def template_exists(pack_name: str, title: str) -> bool:
    """Quick check used by the save flow to decide whether to ask about overwrite."""
    return (pack_templates_dir(pack_name) / f"{slugify(title)}.md").exists()
