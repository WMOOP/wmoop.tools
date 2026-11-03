#!/usr/bin/env python3
"""Validate the code generators themselves.

A generator is only trustworthy if, for a fixed model, it is:

1. **Deterministic** — running it twice produces byte-identical output. Non-determinism
   (dict ordering, set iteration, timestamps) would make every regeneration a noisy diff.
2. **Valid** — every emitted Python module imports, every module has its C# project and
   sources plus the solution that builds them (CI compiles it with the .NET SDK), and its
   TypeScript module next to the kernel and the tsconfig.json that checks them (CI compiles them
   with tsc and imports them with Node.js). Every individual of the model is generated: in Python
   an instance on its class, built (so checked) when the module loads; in C# a static property of
   its class; in TypeScript a static of its class, set at the end of its module.

This script enforces both, for every supported language, without needing the .NET SDK or Node.js.
It uses the canonical model pinned at ``external/wmoop.doc`` (or a sibling ``../wmoop.doc``)
when available, and otherwise falls back to the self-contained fixture model shipped in
``tests/fixtures/model`` so it always runs.

    python tools/check_generated.py                 # auto-detect model
    python tools/check_generated.py --model PATH     # explicit model
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wmoop_tools.compile import validate  # noqa: E402
from wmoop_tools.generators.common import local  # noqa: E402
from wmoop_tools.generators.csharp_gen import generate_csharp, project  # noqa: E402
from wmoop_tools.generators.python_gen import dotted, generate_python, ident  # noqa: E402
from wmoop_tools.generators.typescript_gen import generate_typescript, individual_name  # noqa: E402
from wmoop_tools.loader import load_model  # noqa: E402

FIXTURE_MODEL = ROOT / "tests" / "fixtures" / "model"


def resolve_model(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("WMOOP_MODEL"):
        candidates.append(Path(os.environ["WMOOP_MODEL"]))
    candidates.append(ROOT / "external" / "wmoop.doc" / "model")  # the pinned submodule
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


def check_determinism(model, gen, label: str) -> list[str]:
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        gen(model, d1)
        gen(model, d2)
        return _assert_identical(Path(d1), Path(d2), label)


# Imports every generated module of the `wmoop` namespace package in a clean interpreter.
_IMPORT_ALL = (
    "import importlib, pkgutil, wmoop\n"
    "for m in pkgutil.iter_modules(wmoop.__path__):\n"
    "    importlib.import_module('wmoop.' + m.name)\n"
)


def check_python_valid(model) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        generate_python(model, d)
        pkg = Path(d) / "wmoop"
        for py in sorted(pkg.rglob("*.py")):
            try:
                py_compile.compile(str(py), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append(f"python: generated {py.name} does not compile: {exc}")
        proc = subprocess.run([sys.executable, "-c", _IMPORT_ALL], cwd=d, capture_output=True, text=True)
        if proc.returncode != 0:
            errors.append("python: a generated module failed to import:\n" + proc.stderr.strip())
    return errors


# Reads [id, module, class, attribute] rows and prints the individuals that are not an instance on their class.
_FIND_INDIVIDUALS = (
    "import importlib, json, sys\n"
    "for ident, module, cls, attr in json.load(sys.stdin):\n"
    "    owner = getattr(importlib.import_module('wmoop.' + module), cls)\n"
    "    held = getattr(owner, attr, None)\n"
    "    if not isinstance(held, owner) or str(held.id) != ident:\n"
    "        print(ident)\n"
)


def check_python_individuals(model) -> list[str]:
    rows = [[i.id, dotted(i.module), local(i.instance_of), ident(local(i.id))] for i in model.individuals.values()]
    with tempfile.TemporaryDirectory() as d:
        generate_python(model, d)
        proc = subprocess.run(
            [sys.executable, "-c", _FIND_INDIVIDUALS], cwd=d, input=json.dumps(rows), capture_output=True, text=True
        )
    missing = proc.stdout.split()
    if proc.returncode != 0 or missing:
        return [f"python: individuals not generated on their class: {missing or proc.stderr.strip()}"]
    return []


def check_csharp_present(model) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        generate_csharp(model, d)
        out = Path(d)
        if not (out / "Wmoop.Generated.sln").is_file():
            errors.append("csharp: missing Wmoop.Generated.sln")
        if not (out / "Wmoop.Core" / "Kernel.Gen.cs").is_file():
            errors.append("csharp: missing the kernel, Wmoop.Core/Kernel.Gen.cs")
        if not (out / "Wmoop.Core" / "Units.Gen.cs").is_file():
            errors.append("csharp: missing the unit catalogue, Wmoop.Core/Units.Gen.cs")
        for ind in model.individuals.values():
            source = out / project(ind.module) / f"{local(ind.instance_of)}.Gen.cs"
            if not source.is_file() or f'Id = "{ind.id}",' not in source.read_text(encoding="utf-8"):
                errors.append(f"csharp: individual {ind.id} is missing from {source.name}")
        for proj in sorted(p for p in out.iterdir() if p.is_dir()):
            if not (proj / f"{proj.name}.csproj").is_file():
                errors.append(f"csharp: missing {proj.name}/{proj.name}.csproj")
            if not list(proj.glob("*.Gen.cs")):
                errors.append(f"csharp: {proj.name} has no generated sources")
        for cs in out.rglob("*.cs"):
            if cs.stat().st_size == 0:
                errors.append(f"csharp: emitted empty file {cs.name}")
    return errors


def check_typescript_present(model) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        generate_typescript(model, d)
        out = Path(d)
        for name in ("package.json", "tsconfig.json", "wmoop/_kernel.ts", "wmoop/core.ts"):
            if not (out / name).is_file():
                errors.append(f"typescript: missing {name}")
        for m in model.modules.values():
            source = out / "wmoop" / f"{dotted(m.id)}.ts"
            if not source.is_file():
                errors.append(f"typescript: module {m.id} has no {source.name}")
            elif not source.read_text(encoding="utf-8").startswith("// <auto-generated>"):
                errors.append(f"typescript: {source.name} does not open with the generated-file banner")
        for ind in model.individuals.values():
            source = out / "wmoop" / f"{dotted(ind.module)}.ts"
            cls = local(ind.instance_of)
            text = source.read_text(encoding="utf-8") if source.is_file() else ""
            expected = f'wm.individual({cls}, "{individual_name(model, ind)}", new {cls}({{\n  id: "{ind.id}",'
            if expected not in text:
                errors.append(f"typescript: individual {ind.id} is missing from {source.name}")
        for ts in out.rglob("*.ts"):
            if ts.stat().st_size == 0:
                errors.append(f"typescript: emitted empty file {ts.name}")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate generator determinism and output validity.")
    ap.add_argument("--model", help="model directory (defaults to wmoop.doc, then the bundled fixture)")
    args = ap.parse_args(argv)

    model_dir = resolve_model(args.model)
    print(f"Using model: {model_dir}")
    model = validate(load_model(str(model_dir)))
    print(
        f"Model OK: {len(model.modules)} modules, {len(model.concepts)} concepts, {len(model.roles)} roles, "
        f"{len(model.individuals)} individuals."
    )

    errors: list[str] = []
    errors += check_determinism(model, generate_python, "python/determinism")
    errors += check_determinism(model, generate_csharp, "csharp/determinism")
    errors += check_determinism(model, generate_typescript, "typescript/determinism")
    errors += check_python_valid(model)
    errors += check_python_individuals(model)
    errors += check_csharp_present(model)
    errors += check_typescript_present(model)

    if errors:
        print("\nGenerator validation FAILED:", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        return 1
    print("\nGenerator validation passed: deterministic + valid for python, csharp and typescript.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
