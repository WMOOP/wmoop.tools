"""Command-line entry point: compile the WML model and generate a binding.

Example::

    python -m wmoop_tools --model ../wmoop.doc/model --lang python --out build/py
"""

from __future__ import annotations

import argparse
import os
import sys

from .compile import ModelError, validate
from .loader import load_model


def _generate(wm, lang: str, out: str) -> list:
    written: list = []
    if lang in ("python", "all"):
        from .generators.python_gen import generate_python

        written += generate_python(wm, out)
    if lang in ("csharp", "all"):
        from .generators.csharp_gen import generate_csharp

        written += generate_csharp(wm, out)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="wmoop-tools",
        description="Compile the WML World Model and generate language bindings.",
    )
    ap.add_argument("--model", required=True, help="path to the model/ directory (WML source of truth)")
    ap.add_argument("--lang", choices=["python", "csharp", "all"], default="python", help="target language")
    ap.add_argument("--out", help="output directory (required unless --check)")
    ap.add_argument(
        "--check",
        action="store_true",
        help="validate the model only; do not generate any code (useful as a CI gate)",
    )
    args = ap.parse_args(argv)

    if not args.check and not args.out:
        ap.error("--out is required unless --check is given")

    try:
        wm = validate(load_model(args.model))
    except ModelError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(
        f"Loaded and validated: {len(wm.modules)} modules, {len(wm.concepts)} concepts, "
        f"{len(wm.roles)} roles, {len(wm.enumerations)} enumerations."
    )

    if args.check:
        print("Model is valid.")
        return 0

    written = _generate(wm, args.lang, args.out)
    print(f"Generated {len(written)} file(s) into {args.out}:")
    for w in written:
        print("  " + os.path.relpath(w, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
