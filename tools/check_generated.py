#!/usr/bin/env python3
"""Validate the code generators themselves.

A generator is only trustworthy if, for a fixed model, it is:

1. **Deterministic** — running it twice produces byte-identical output. Non-determinism
   (dict ordering, set iteration, timestamps) would make every regeneration a noisy diff.
2. **Valid** — the emitted Python is importable and the emitted C# is at least present and
   non-empty for every module.

This script enforces both, for every supported language, without needing the .NET SDK.
It uses the external canonical model when available and otherwise falls back to the
self-contained fixture model shipped in ``tests/fixtures/model`` so it always runs.

    python tools/check_generated.py                 # auto-detect model
    python tools/check_generated.py --model PATH     # explicit model
"""

from __future__ import annotations

import argparse
import filecmp
import os
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wmoop_tools.compile import validate  # noqa: E402
from wmoop_tools.generators.csharp_gen import generate_csharp  # noqa: E402
from wmoop_tools.generators.python_gen import generate_python  # noqa: E402
from wmoop_tools.loader import load_model  # noqa: E402

FIXTURE_MODEL = ROOT / "tests" / "fixtures" / "model"


def resolve_model(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("WMOOP_MODEL"):
        candidates.append(Path(os.environ["WMOOP_MODEL"]))
    candidates.append(ROOT.parent / "wmoop.doc" / "model")
    candidates.append(FIXTURE_MODEL)
    for c in candidates:
        if c.is_dir():
            return c.resolve()
    raise SystemExit("No model directory found (tried: " + ", ".join(str(c) for c in candidates) + ")")


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _assert_identical(a: Path, b: Path, label: str) -> list[str]:
    errors = []
    files_a, files_b = _tree(a), _tree(b)
    if files_a != files_b:
        only_a = sorted(files_a - files_b)
        only_b = sorted(files_b - files_a)
        errors.append(f"{label}: file sets differ (only in run 1: {only_a}; only in run 2: {only_b})")
    for rel in sorted(files_a & files_b):
        if not filecmp.cmp(a / rel, b / rel, shallow=False):
            errors.append(f"{label}: non-deterministic output in {rel}")
    return errors


def check_determinism(model, gen, out_name: str, label: str) -> list[str]:
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        gen(model, d1)
        gen(model, d2)
        return _assert_identical(Path(d1) / out_name, Path(d2) / out_name, label)


def check_python_valid(model) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        generate_python(model, d)
        pkg = Path(d) / "wmoop_model"
        for py in sorted(pkg.rglob("*.py")):
            try:
                py_compile.compile(str(py), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append(f"python: generated {py.name} does not compile: {exc}")
        # Import the package in a clean subprocess to prove it actually loads.
        proc = subprocess.run(
            [sys.executable, "-c", "import importlib; importlib.import_module('wmoop_model')"],
            cwd=d,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            errors.append("python: generated package failed to import:\n" + proc.stderr.strip())
    return errors


def check_csharp_present(model) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        generate_csharp(model, d)
        proj = Path(d) / "Wmoop.Generated"
        if not (proj / "Wmoop.Generated.csproj").is_file():
            errors.append("csharp: missing Wmoop.Generated.csproj")
        cs_files = list(proj.rglob("*.cs"))
        if not cs_files:
            errors.append("csharp: no .cs files were emitted")
        for cs in cs_files:
            if cs.stat().st_size == 0:
                errors.append(f"csharp: emitted empty file {cs.name}")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate generator determinism and output validity.")
    ap.add_argument("--model", help="model directory (defaults to wmoop.doc, then the bundled fixture)")
    args = ap.parse_args(argv)

    model_dir = resolve_model(args.model)
    print(f"Using model: {model_dir}")
    model = validate(load_model(str(model_dir)))
    print(f"Model OK: {len(model.modules)} modules, {len(model.concepts)} concepts, {len(model.roles)} roles.")

    errors: list[str] = []
    errors += check_determinism(model, generate_python, "wmoop_model", "python/determinism")
    errors += check_determinism(model, generate_csharp, "Wmoop.Generated", "csharp/determinism")
    errors += check_python_valid(model)
    errors += check_csharp_present(model)

    if errors:
        print("\nGenerator validation FAILED:", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        return 1
    print("\nGenerator validation passed: deterministic + valid for python and csharp.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
