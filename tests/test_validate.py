"""Validation: the structural invariants enforced by ``compile.validate``."""

from __future__ import annotations

import pytest

from wmoop_tools.compile import (
    MAX_INHERITANCE_DEPTH,
    ModelError,
    concept_chain,
    inherited_properties,
    validate,
)
from wmoop_tools.model import Concept, Module, Role, WorldModel


def _wm(concepts=(), roles=(), modules=()) -> WorldModel:
    wm = WorldModel()
    for c in concepts:
        wm.concepts[c.id] = c
    for r in roles:
        wm.roles[r.id] = r
    for m in modules:
        wm.modules[m.id] = m
    return wm


def test_fixture_model_is_valid(world_model):
    assert validate(world_model) is world_model


def test_extends_unknown_concept():
    wm = _wm(concepts=[Concept(id="A", name="A", extends="Ghost")])
    with pytest.raises(ModelError, match="extends unknown"):
        validate(wm)


def test_played_by_unknown_concept():
    wm = _wm(roles=[Role(id="R", name="R", played_by="Ghost")])
    with pytest.raises(ModelError, match="played_by unknown"):
        validate(wm)


def test_module_dependency_cycle():
    wm = _wm(modules=[Module(id="m1", depends_on=["m2"]), Module(id="m2", depends_on=["m1"])])
    with pytest.raises(ModelError, match="dependency cycle"):
        validate(wm)


def test_inheritance_cycle():
    wm = _wm(concepts=[Concept(id="A", name="A", extends="B"), Concept(id="B", name="B", extends="A")])
    with pytest.raises(ModelError, match="inheritance cycle"):
        validate(wm)


def test_inheritance_depth_limit():
    n = MAX_INHERITANCE_DEPTH + 2
    concepts = [Concept(id=f"C{i}", name=f"C{i}", extends=(f"C{i - 1}" if i else None)) for i in range(n)]
    wm = _wm(concepts=concepts)
    with pytest.raises(ModelError, match="depth exceeds"):
        validate(wm)


def test_shallow_inheritance_within_limit_passes():
    n = MAX_INHERITANCE_DEPTH  # depth == limit is allowed
    concepts = [Concept(id=f"C{i}", name=f"C{i}", extends=(f"C{i - 1}" if i else None)) for i in range(n)]
    assert validate(_wm(concepts=concepts)) is not None


def test_external_dependency_is_ignored():
    # A dependency on a module not present in this model (e.g. wmoop.core) must not fail.
    wm = _wm(modules=[Module(id="m1", depends_on=["wmoop.external"])])
    assert validate(wm) is not None


def test_concept_chain_is_root_first(world_model):
    person = world_model.concepts["wmoop.animals/Person"]
    chain = [c.id for c in concept_chain(world_model, person)]
    assert chain == [
        "wmoop.base/Thing",
        "wmoop.animals/Animal",
        "wmoop.animals/Mammal",
        "wmoop.animals/Person",
    ]


def test_inherited_properties_exclude_own(world_model):
    person = world_model.concepts["wmoop.animals/Person"]
    inherited = {p.name for p in inherited_properties(world_model, person)}
    assert "label" in inherited  # from Thing
    assert "legCount" in inherited  # from Animal
    assert "fullName" not in inherited  # Person's own property
