"""Shared pytest fixtures.

The fixture model under ``tests/fixtures/model`` lets the unit tests exercise the whole
pipeline (load → validate → generate → import) without the external ``wmoop.doc`` repo.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from wmoop_tools.compile import validate
from wmoop_tools.generators.python_gen import generate_python
from wmoop_tools.loader import load_model

FIXTURE_MODEL = Path(__file__).parent / "fixtures" / "model"
FIXTURE_MODULES = ("base", "animals", "society")
# The generated namespace package and the binding-side extension package.
_GENERATED_ROOTS = ("wmoop", "wmoop_ext")


@pytest.fixture(scope="session")
def fixture_model_dir() -> Path:
    return FIXTURE_MODEL


@pytest.fixture(scope="session")
def world_model():
    """The loaded + validated fixture model."""
    return validate(load_model(str(FIXTURE_MODEL)))


def forget_generated() -> None:
    for name in list(sys.modules):
        if name.split(".")[0] in _GENERATED_ROOTS:
            del sys.modules[name]


def import_generated(*roots: Path, modules=FIXTURE_MODULES) -> SimpleNamespace:
    """Import fresh ``wmoop.<module>`` modules, with ``roots`` first on ``sys.path``."""
    forget_generated()
    for root in reversed(roots):
        sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    loaded = {m: importlib.import_module(f"wmoop.{m}") for m in modules}
    return SimpleNamespace(**loaded, core=importlib.import_module("wmoop.core"))


@pytest.fixture
def isolated_imports(tmp_path):
    """Drop generated modules and tmp_path entries from sys.path after the test."""
    try:
        yield tmp_path
    finally:
        forget_generated()
        sys.path[:] = [p for p in sys.path if not p.startswith(str(tmp_path))]


@pytest.fixture
def generated_python(isolated_imports, world_model):
    """Generate the Python binding from the fixture model and import it fresh."""
    out = isolated_imports / "gen"
    generate_python(world_model, str(out))
    return import_generated(out)
