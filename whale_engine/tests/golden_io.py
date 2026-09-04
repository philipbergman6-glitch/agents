"""Shared writer for the make_golden_*.py scripts.

`--check` regenerates in memory and compares against the committed file
instead of overwriting it, so CI can prove the goldens still match the code
without trusting anyone to have rerun the script.
"""

import json
import sys
from pathlib import Path


def render(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def emit(path: Path, obj, check: bool) -> bool:
    """Write `obj` to `path`, or in check mode report whether it already matches.

    Returns True when the committed file is (now) identical to `obj`.
    """
    text = render(obj)
    if check:
        current = path.read_text() if path.exists() else None
        if current == text:
            print(f"ok       {path}")
            return True
        print(f"MISMATCH {path}" + ("" if current is not None else " (missing)"))
        return False
    path.write_text(text)
    print(f"wrote    {path}")
    return True


def check_flag() -> bool:
    return "--check" in sys.argv[1:]


def finish(results: list[bool], check: bool) -> None:
    if check and not all(results):
        print(
            "golden files differ from the current engine output; "
            "rerun without --check to regenerate"
        )
        sys.exit(1)
