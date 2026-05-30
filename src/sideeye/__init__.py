"""SideEye — a precise, local text linter with pluggable rule packs.

The default pack is prompt-safety (LLM prompt + agent-trace safety).
A markdown lint pack ships with the package. Adding a new pack is a
single Python file: see `src/sideeye/packs/markdown.py` for a template.
"""

__version__ = "0.2.0"
__author__ = "Roberta Carraro"

# Generic surface (new)
# Backwards-compatible surface
from sideeye.models import Category, Finding, RiskCategory, RiskLevel, ScanResult, Severity
from sideeye.packs import (
    Pack,
    PackRule,
    Template,
    get_pack,
    list_packs,
    pack_for_file,
    pack_for_text,
)
from sideeye.scanner import scan_prompt, scan_text, scan_trace

__all__ = [
    "__version__",
    # generic
    "Category",
    "Finding",
    "Pack",
    "PackRule",
    "ScanResult",
    "Severity",
    "Template",
    "get_pack",
    "list_packs",
    "pack_for_file",
    "pack_for_text",
    "scan_text",
    # legacy
    "RiskCategory",
    "RiskLevel",
    "scan_prompt",
    "scan_trace",
]
