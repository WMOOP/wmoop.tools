"""Shared pytest fixtures.

The fixture model under ``tests/fixtures/model`` lets the unit tests exercise the whole
pipeline (load → validate → generate → import) without the external ``wmoop.doc`` repo.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from wmoop_tools.compile import validate
from wmoop_tools.generators.python_gen import generate_python
from wmoop_tools.loader import load_model

FIXTURE_MODEL = Path(__file__).parent / "fixtures" / "model"


@pytest.fixture(scope="session")
def fixture_model_dir() -> Path:
    return FIXTURE_MODEL


@pytest.fixture(scope="session")
def world_model():
    """The loaded + validated fixture model."""
    return validate(load_model(str(FIXTURE_MODEL)))


def _forget_generated() -> None:
    for name in list(sys.modules):
        if name == "wmoop_model" or name.startswith("wmoop_model."):
            del sys.modules[name]


@pytest.fixture
def generated_python(tmp_path, world_model):
    """Generate the Python binding from the fixture model and import it fresh."""
    out = tmp_path / "gen"
    generate_python(world_model, str(out))
    _forget_generated()
    sys.path.insert(0, str(out))
    importlib.invalidate_caches()
    try:
        yield importlib.import_module("wmoop_model")
    finally:
        _forget_generated()
        if str(out) in sys.path:
            sys.path.remove(str(out))
