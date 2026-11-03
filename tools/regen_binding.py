#!/usr/bin/env python3
"""Regenerate, or verify, the generated code of a WMOOP binding repository.

A binding repository (``wmoop.net``, ``wmoop.py``, ``wmoop.js``, ...) pins two git submodules and
commits the generator output under one directory:

    external/wmoop.doc     the canonical model, with the validator and grammar that go with it
    external/wmoop.tools   this toolchain
    generated/             the output: never edited by hand, only rewritten by this script

Run from the binding's root, the script:

1. **Validates** the model with the validator shipped in the *same* wmoop.doc commit
   (``schema/validate_wml.py --strict``), so a binding never applies other rules than the
   model was checked with.
2. **Generates** into an emptied directory, so concepts deleted from the model disappear.
3. **Records its inputs** in ``generated/WMOOP_SOURCE.json``: the commits of wmoop.doc, of the
   grammar it pins and of wmoop.tools. The file changes whenever a pin moves, so a pin bump
   without regeneration is caught too.

``--check`` writes nothing: it generates into a temporary directory and compares the result with
the committed output (line endings ignored, so ``core.autocrlf`` cannot cause noise). Any
difference exits 1 - the CI drift gate.

    python external/wmoop.tools/tools/regen_binding.py --lang csharp           # regenerate
    python external/wmoop.tools/tools/regen_binding.py --lang csharp --check   # CI gate
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the wmoop.tools checkout
sys.path.insert(0, str(ROOT))

from wmoop_tools.compile import ModelError, validate  # noqa: E402
from wmoop_tools.generators.csharp_gen import generate_csharp  # noqa: E402
from wmoop_tools.generators.python_gen import generate_python  # noqa: E402
from wmoop_tools.generators.typescript_gen import generate_typescript  # noqa: E402
from wmoop_tools.loader import load_model  # noqa: E402

GENERATORS = {"python": generate_python, "csharp": generate_csharp, "typescript": generate_typescript}
SOURCE_FILE = "WMOOP_SOURCE.json"


def _checkout_head(path: Path) -> str:
    """The commit checked out at ``path``, which must be the root of its own repository."""
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-prefix", "HEAD"], capture_output=True, text=True
    )
    lines = proc.stdout.splitlines()
    # An uninitialised submodule is an empty folder of the parent repo: its prefix is not empty.
    if proc.returncode != 0 or len(lines) != 2 or lines[0]:
        raise SystemExit(f"{path} is not a checked-out repository (run: git submodule update --init --recursive)")
    return lines[1]


def _validate_model(doc: Path) -> None:
    validator = doc / "schema" / "validate_wml.py"
    if not validator.is_file():
        raise SystemExit(f"{validator} not found: --doc must point at a wmoop.doc checkout")
    # -B: no __pycache__ inside the wmoop.doc submodule. That untracked content would make the
    # submodule look modified, and the regen workflow would then try to commit a change it cannot.
    if subprocess.run([sys.executable, "-B", str(validator), "--strict"], cwd=doc).returncode != 0:
        raise SystemExit("the model fails wmoop.doc's own validator; nothing was generated")


def _reset(out: Path) -> None:
    """Empty ``out`` - only if it is empty already or this script produced it."""
    if out.exists():
        if any(out.iterdir()) and not (out / SOURCE_FILE).is_file():
            raise SystemExit(f"refusing to empty {out}: it holds no {SOURCE_FILE}, so it is not generated output")
        shutil.rmtree(out)
    out.mkdir(parents=True)


def generate(doc: Path, lang: str, out: Path) -> dict:
    """Validate the model, then write the binding and its provenance into ``out``."""
    _validate_model(doc)
    try:
        wm = validate(load_model(str(doc / "model")))
    except ModelError as exc:
        raise SystemExit(str(exc)) from exc
    grammar = doc / "external" / "wmoop.json"
    source = {
        "lang": lang,
        "wmoop.doc": _checkout_head(doc),
        # A wmoop.doc from before the grammar became a submodule has no external/wmoop.json.
        "wmoop.json": _checkout_head(grammar) if grammar.exists() else None,
        "wmoop.tools": _checkout_head(ROOT),
    }
    _reset(out)
    GENERATORS[lang](wm, str(out))
    (out / SOURCE_FILE).write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8", newline="\n")
    return source


def _files(root: Path, git: bool) -> set[str]:
    """Files under ``root``; with ``git``, only those git would commit (build output is ignored)."""
    if not root.is_dir():
        return set()
    if git:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
        )
        if proc.returncode == 0:
            return {f for f in proc.stdout.decode("utf-8").split("\0") if f and (root / f).is_file()}
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _differences(expected: Path, actual: Path) -> list[str]:
    def read(p: Path) -> bytes:
        return p.read_bytes().replace(b"\r\n", b"\n")

    want, have = _files(expected, git=False), _files(actual, git=True)
    diffs = [f"missing: {f}" for f in sorted(want - have)]
    diffs += [f"no longer generated: {f}" for f in sorted(have - want)]
    diffs += [f"differs: {f}" for f in sorted(want & have) if read(expected / f) != read(actual / f)]
    return diffs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Regenerate, or verify, a WMOOP binding's generated code.")
    ap.add_argument("--lang", required=True, choices=sorted(GENERATORS), help="target language")
    ap.add_argument("--doc", default="external/wmoop.doc", help="the wmoop.doc checkout (default: %(default)s)")
    ap.add_argument("--out", default="generated", help="the committed output directory (default: %(default)s)")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if the committed output is stale")
    args = ap.parse_args(argv)
    doc, out = Path(args.doc).resolve(), Path(args.out).resolve()

    if not args.check:
        src = generate(doc, args.lang, out)
        print(f"Regenerated {args.out}/ from wmoop.doc@{src['wmoop.doc'][:7]} + wmoop.tools@{src['wmoop.tools'][:7]}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        src = generate(doc, args.lang, Path(tmp) / "out")
        diffs = _differences(Path(tmp) / "out", out)
    if diffs:
        print(
            f"{args.out}/ is STALE versus the pinned wmoop.doc@{src['wmoop.doc'][:7]} + wmoop.tools@{src['wmoop.tools'][:7]}:"
        )
        for d in diffs:
            print(f"  - {d}")
        print(f"\nRegenerate: python {Path(sys.argv[0]).as_posix()} --lang {args.lang}")
        return 1
    print(f"OK - {args.out}/ matches wmoop.doc@{src['wmoop.doc'][:7]} + wmoop.tools@{src['wmoop.tools'][:7]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
