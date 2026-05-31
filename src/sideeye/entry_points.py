"""CLI entry points for SideEye.

Modes:
  sideeye                          launch the TUI (default pack auto-detected)
  sideeye --pack markdown          launch the TUI with a specific pack
  sideeye packs                    list available packs
  sideeye scan ...                 one-shot scan with pretty or JSON output
  sideeye check ...                CI gate: exit 1 if HIGH+ (configurable)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn

from rich.console import Console
from rich.text import Text

from sideeye import __version__
from sideeye.models import ScanResult
from sideeye.packs import (
    DEFAULT_PACK,
    get_pack,
    list_packs,
    pack_for_file,
    pack_for_text,
)
from sideeye.packs.base import Pack
from sideeye.scanner import scan_text


def run() -> NoReturn:
    parser = argparse.ArgumentParser(
        prog="sideeye",
        description=(
            "Local text linter with pluggable rule packs. "
            "No network, no model calls, no telemetry."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-p", "--pack",
        help=f"Rule pack to use. Default: auto-detect, fallback to '{DEFAULT_PACK}'.",
    )

    subparsers = parser.add_subparsers(dest="command")

    # packs (list)
    subparsers.add_parser("packs", help="List installed rule packs")

    # templates (list / path)
    tpl_p = subparsers.add_parser("templates", help="List user templates")
    tpl_p.add_argument(
        "-p", "--pack",
        help="Filter to a specific pack (default: all)",
    )
    tpl_p.add_argument(
        "--path", action="store_true",
        help="Print the templates root directory and exit",
    )

    # scan
    scan_p = subparsers.add_parser("scan", help="Scan input and print findings")
    scan_p.add_argument("text", nargs="?", help="Text to scan. If omitted, reads stdin.")
    scan_p.add_argument("-p", "--pack", help="Rule pack to use (overrides global --pack)")
    scan_p.add_argument(
        "-f", "--file",
        help="Read input from FILE. Pack auto-detected from extension if --pack unset.",
    )
    scan_p.add_argument(
        "-d", "--designer",
        action="store_true",
        help="Force optional rules on (prompt-safety: designer-only rules)",
    )
    scan_p.add_argument("-j", "--json", action="store_true", help="Output JSON")
    scan_p.add_argument(
        "--trace",
        action="store_true",
        help="Treat input as agent trace (prompt-safety pack only)",
    )
    scan_p.add_argument("--no-color", action="store_true", help="Disable color")

    # check (CI gate)
    check_p = subparsers.add_parser(
        "check",
        help="CI gate. Exit 1 if any finding at --fail-on or worse.",
    )
    check_p.add_argument("text", nargs="?", help="Text to scan. If omitted, reads stdin.")
    check_p.add_argument("-p", "--pack", help="Rule pack to use")
    check_p.add_argument("-f", "--file", help="Read input from FILE")
    check_p.add_argument("-d", "--designer", action="store_true")
    check_p.add_argument("--trace", action="store_true")
    check_p.add_argument(
        "--fail-on",
        choices=["critical", "high", "medium", "low"],
        default="high",
        help="Lowest severity that causes a non-zero exit (default: high)",
    )
    check_p.add_argument("-q", "--quiet", action="store_true")

    args = parser.parse_args()

    if args.command == "packs":
        _cmd_packs()
    elif args.command == "templates":
        _cmd_templates(args)
    elif args.command == "scan":
        _cmd_scan(args)
    elif args.command == "check":
        _cmd_check(args)
    else:
        # Default: launch TUI
        from sideeye.tui.app import SideEyeApp
        # Resolve pack from --pack flag if provided.
        initial_pack = None
        if args.pack:
            try:
                initial_pack = get_pack(args.pack)
            except KeyError as e:
                print(f"error: {e}", file=sys.stderr)
                sys.exit(2)
        SideEyeApp(initial_pack=initial_pack).run()
        sys.exit(0)


# --------------------------------------------------------------------------- #
# packs (list)
# --------------------------------------------------------------------------- #

def _cmd_packs() -> NoReturn:
    console = Console(force_terminal=True, highlight=False)
    # Reload packs that have user config (personal-info reads a TOML file).
    # The global singletons cache their rules on construction; if the user
    # edited their config after import, we want the fresh view.
    for pack in list_packs():
        reload_fn = getattr(pack, "reload", None)
        if callable(reload_fn):
            reload_fn()

    for pack in list_packs():
        is_default = pack.name == DEFAULT_PACK
        head = Text()
        head.append(pack.name, style="bold")
        if is_default:
            head.append("  (default)", style="dim italic")
        console.print(head)
        console.print(Text(f"  {pack.description}", style="dim"))
        if pack.file_extensions:
            exts = ", ".join(pack.file_extensions)
            console.print(Text(f"  files: {exts}", style="dim"))
        n_rules = len(pack.rules)
        n_optional = sum(1 for r in pack.rules if r.optional)
        rules_line = f"  rules: {n_rules}"
        if n_optional:
            rules_line += f" ({n_optional} optional)"
        # Show pack-specific status (e.g. "config: ~/.config/sideeye/personal.toml")
        configured = getattr(pack, "configured", None)
        config_path = getattr(pack, "config_path", None)
        if configured is False:
            rules_line += "   [not configured]"
        elif config_path is not None:
            rules_line += f"   config: {config_path}"
        console.print(Text(rules_line, style="dim"))
        console.print()
    sys.exit(0)


# --------------------------------------------------------------------------- #
# templates
# --------------------------------------------------------------------------- #

def _cmd_templates(args: argparse.Namespace) -> NoReturn:
    from sideeye.user_templates import load_user_templates, templates_root

    console = Console(force_terminal=True, highlight=False)

    if args.path:
        print(templates_root())
        sys.exit(0)

    root = templates_root()
    if not root.exists():
        console.print(Text("No user templates yet. Save one with ctrl+shift+s in the TUI.", style="dim"))
        console.print(Text(f"Templates will live at: {root}", style="dim"))
        sys.exit(0)

    # Iterate over per-pack subdirs.
    pack_dirs = sorted([d for d in root.iterdir() if d.is_dir()])
    if args.pack:
        pack_dirs = [d for d in pack_dirs if d.name == args.pack]
        if not pack_dirs:
            console.print(Text(f"No user templates for pack '{args.pack}'.", style="dim"))
            sys.exit(0)

    any_found = False
    for pack_dir in pack_dirs:
        templates = load_user_templates(pack_dir.name)
        if not templates:
            continue
        any_found = True
        console.print(Text(pack_dir.name, style="bold"))
        for tpl in templates:
            head = Text("  ")
            head.append("● ", style="bold green")
            head.append(tpl.title, style="bold")
            head.append(f"   {tpl.category}", style="dim italic")
            console.print(head)
            if tpl.description:
                console.print(Text(f"    {tpl.description}", style="dim"))
        console.print()

    if not any_found:
        console.print(Text("No user templates yet. Save one with ctrl+shift+s in the TUI.", style="dim"))
        console.print(Text(f"Templates directory: {root}", style="dim"))

    sys.exit(0)


# --------------------------------------------------------------------------- #
# scan
# --------------------------------------------------------------------------- #

def _resolve_input_and_pack(args: argparse.Namespace) -> tuple[str, Pack]:
    """Read input and resolve which pack to use.

    Resolution order for the pack:
      1. --pack on the subcommand (most specific)
      2. --pack on the global parser
      3. File extension (if --file passed)
      4. Content auto-detection
      5. Default pack
    """
    # Read input
    if args.file:
        path = Path(args.file).expanduser()
        if not path.exists():
            print(f"error: file not found: {path}", file=sys.stderr)
            sys.exit(2)
        text = path.read_text(encoding="utf-8", errors="replace")
        file_path: Path | None = path
    elif args.text:
        text = args.text
        file_path = None
    else:
        if sys.stdin.isatty():
            print("error: no input. Pass text, use --file, or pipe via stdin.", file=sys.stderr)
            sys.exit(2)
        text = sys.stdin.read()
        file_path = None

    if not text.strip():
        print("error: empty input", file=sys.stderr)
        sys.exit(2)

    # Pack resolution
    pack_name = args.pack
    if pack_name:
        try:
            pack = get_pack(pack_name)
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)
    elif file_path is not None:
        pack = pack_for_file(file_path) or pack_for_text(text)
    else:
        pack = pack_for_text(text)

    # Reload pack-specific config (e.g. personal-info reads a TOML file).
    reload_fn = getattr(pack, "reload", None)
    if callable(reload_fn):
        reload_fn()

    # Propagate file context to the pack so file-aware rules can use it.
    # Packs that don't care about file paths just ignore this attribute.
    if hasattr(pack, "file_path"):
        pack.file_path = file_path

    return text, pack


def _cmd_scan(args: argparse.Namespace) -> NoReturn:
    text, pack = _resolve_input_and_pack(args)

    if args.trace and pack.name == "prompt-safety":
        # Use the trace-aware scanner for prompt-safety only
        from sideeye.scanner import scan_trace
        result = scan_trace(text, designer_mode=args.designer)
    else:
        result = scan_text(text, pack=pack, force_optional=args.designer)

    if args.json:
        print(result.model_dump_json_pretty())
        sys.exit(0)

    _print_pretty(result, pack, no_color=args.no_color)
    sys.exit(0)


def _print_pretty(result: ScanResult, pack: Pack, no_color: bool = False) -> None:
    console = Console(no_color=no_color, force_terminal=not no_color, highlight=False)

    # Header: pack name + severity + counts + token count
    sev = result.overall_risk
    head = Text()
    head.append(sev.glyph, style=f"bold {sev.color}")
    head.append("  ")
    head.append(sev.value.upper(), style=f"bold {sev.color}")
    head.append("   ")
    if result.findings:
        head.append(result.status_line())
    else:
        head.append("no issues detected", style="dim")
    head.append("   ")
    head.append(f"{result.token_count} tok", style="dim")
    head.append(f"   pack: {pack.name}", style="dim italic")
    console.print(head)

    if not result.findings:
        return

    console.print()

    for f in result.findings:
        sev_line = Text()
        sev_line.append(f.severity.value.upper().ljust(8), style=f"bold {f.severity.color}")
        sev_line.append(f.short_category, style="bold")
        console.print(sev_line)

        console.print(Text(f"         {f.message}"))

        if f.excerpt and f.excerpt != "(whitespace)":
            excerpt = f.excerpt if len(f.excerpt) < 140 else f.excerpt[:137] + "…"
            console.print(Text(f"         “{excerpt}”", style="dim italic"))

        if f.suggestion:
            console.print(Text(f"         → {f.suggestion}", style=f.severity.color))

        console.print()


# --------------------------------------------------------------------------- #
# check (CI gate)
# --------------------------------------------------------------------------- #

_SEV_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _cmd_check(args: argparse.Namespace) -> NoReturn:
    text, pack = _resolve_input_and_pack(args)

    if args.trace and pack.name == "prompt-safety":
        from sideeye.scanner import scan_trace
        result = scan_trace(text, designer_mode=args.designer)
    else:
        result = scan_text(text, pack=pack, force_optional=args.designer)

    threshold = _SEV_RANK[args.fail_on]
    actual = _SEV_RANK[result.overall_risk.value]

    if not args.quiet:
        console = Console(force_terminal=True, highlight=False)
        status_text = result.status_line() if result.findings else "no issues detected"
        if actual >= threshold:
            console.print(
                f"[bold {result.overall_risk.color}]FAIL[/]: "
                f"{status_text} (pack: {pack.name}, threshold: {args.fail_on})"
            )
        else:
            console.print(
                f"[bold green]OK[/]: {status_text} "
                f"(pack: {pack.name}, threshold: {args.fail_on})"
            )

    sys.exit(1 if actual >= threshold else 0)


if __name__ == "__main__":
    run()
