"""Command-line entry point: compile the WML model and generate a binding.

Example::

    python -m wmoop_tools --model ../wmoop.doc/model --lang python --out build/py
"""
from __future__ import annotations

import argparse
import os
import sys

from .compile import validate
from .loader import load_model


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="wmoop-tools",
        description="Compile the WML World Model and generate language bindings.",
    )
    ap.add_argument("--model", required=True, help="path to the model/ directory (WML source of truth)")
    ap.add_argument("--lang", choices=["python", "csharp"], default="python", help="target language")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args(argv)

    wm = validate(load_model(args.model))
    print(f"Loaded and validated: {len(wm.modules)} modules, {len(wm.concepts)} concepts, "
          f"{len(wm.roles)} roles, {len(wm.enumerations)} enumerations.")

    if args.lang == "python":
        from .generators.python_gen import generate_python
        written = generate_python(wm, args.out)
    else:
        from .generators.csharp_gen import generate_csharp
        written = generate_csharp(wm, args.out)

    print(f"Generated {len(written)} file(s) into {args.out}:")
    for w in written:
        print("  " + os.path.relpath(w, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
