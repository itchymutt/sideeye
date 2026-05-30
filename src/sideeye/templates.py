"""Legacy templates module.

Templates now live in their pack. This module re-exports the prompt-safety
pack's templates as `TEMPLATES` for backwards compatibility with old code
that imports them directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from sideeye.packs.base import Template
from sideeye.packs.prompt_safety import TEMPLATES as _PROMPT_SAFETY_TEMPLATES


# Legacy shape used by the old TUI. Older callers expect a `prompt` field
# instead of `body`. We expose both via a thin adapter.
@dataclass(frozen=True)
class CreativeTemplate:
    id: str
    title: str
    category: str
    description: str
    prompt: str
    tags: list[str]


def _adapt(t: Template) -> CreativeTemplate:
    return CreativeTemplate(
        id=t.id,
        title=t.title,
        category=t.category,
        description=t.description,
        prompt=t.body,
        tags=[],
    )


TEMPLATES: list[CreativeTemplate] = [_adapt(t) for t in _PROMPT_SAFETY_TEMPLATES]


def get_template_by_id(template_id: str) -> CreativeTemplate | None:
    return next((t for t in TEMPLATES if t.id == template_id), None)
