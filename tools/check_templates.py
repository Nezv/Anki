#!/usr/bin/env python3
"""Check card templates for the bug class that renders cards blank.

Anki re-executes a template's <script> in the SAME global scope as you move
between cards. A top-level `const` or `let` therefore throws

    SyntaxError: Identifier 'X' has already been declared

on the second card, which kills the whole script block. The divs still get
their CSS, so you see styled but empty boxes rather than an error — and the
first card of a session renders fine, which makes it easy to misread as a
styling problem.

The fix is to wrap the template's script in an IIFE so nothing reaches global
scope:

    <script>
    (function () {
      "use strict";
      ...
    })();
    </script>

Usage:
    python tools/check_templates.py            # every notetype
    python tools/check_templates.py hanzi      # just one

Exits non-zero if any template would break.
"""
import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTETYPES_DIR = REPO_ROOT / "notetypes"

SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
# A declaration at column 0 inside a script block is top-level, i.e. global.
TOP_LEVEL_DECL_RE = re.compile(r"^(const|let|class)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)


def check_template(path, problems):
    html = path.read_text(encoding="utf-8")
    rel = path.relative_to(REPO_ROOT)

    for script in SCRIPT_RE.findall(html):
        for match in TOP_LEVEL_DECL_RE.finditer(script):
            kind, name = match.group(1), match.group(2)
            line = script[: match.start()].count("\n") + 1
            problems.append(
                f"{rel} (script line {line}): top-level `{kind} {name}` — redeclared on "
                f"the second card, blanking it. Wrap the script in an IIFE."
            )


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("notetypes", nargs="*", help="notetype slugs (default: all)")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    slugs = args.notetypes or sorted(
        d.name for d in NOTETYPES_DIR.iterdir() if d.is_dir()
    )

    problems = []
    checked = 0
    for slug in slugs:
        directory = NOTETYPES_DIR / slug
        if not directory.is_dir():
            sys.exit(f"No such notetype: {slug}")
        for name in ("front.html", "back.html"):
            path = directory / name
            if path.is_file():
                check_template(path, problems)
                checked += 1

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        sys.exit(f"\n{len(problems)} problem(s) across {checked} template(s)")
    print(f"OK — {checked} template(s) checked, no global declarations")


if __name__ == "__main__":
    main()
