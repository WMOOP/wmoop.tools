"""Loader: WML (*.wml.yaml) folders -> WorldModel."""

from __future__ import annotations


def test_modules_loaded(world_model):
    assert set(world_model.modules) == {"wmoop.base", "wmoop.animals", "wmoop.society"}


def test_module_metadata(world_model):
    animals = world_model.modules["wmoop.animals"]
    assert animals.version == "1.0.0"
    assert animals.title == "Animals"
    assert animals.dir_name == "animals"


def test_depends_on_parsed(world_model):
    assert world_model.modules["wmoop.animals"].depends_on == ["wmoop.base"]
    assert world_model.modules["wmoop.society"].depends_on == ["wmoop.animals"]


def test_concepts_indexed(world_model):
    for cid in ("wmoop.base/Thing", "wmoop.animals/Animal", "wmoop.animals/Person"):
        assert cid in world_model.concepts
    assert world_model.concepts["wmoop.animals/Person"].module == "wmoop.animals"


def test_roles_indexed(world_model):
    citizen = world_model.roles["wmoop.society/Citizen"]
    assert citizen.played_by == "wmoop.animals/Person"
    assert citizen.module == "wmoop.society"


def test_role_bearing_inferred(world_model):
    # Person is the played_by target of a role, so it is role-bearing.
    assert "wmoop.animals/Person" in world_model.role_bearing


def test_enumeration_values(world_model):
    sex = world_model.enumerations["wmoop.animals/Sex"]
    assert [v.id for v in sex.values] == ["male", "female"]


def test_property_fields(world_model):
    person = world_model.concepts["wmoop.animals/Person"]
    by_name = {p.name: p for p in person.properties}
    assert by_name["fullName"].required is True
    assert by_name["fullName"].type == "string"
    animal = world_model.concepts["wmoop.animals/Animal"]
    mass = next(p for p in animal.properties if p.name == "mass")
    assert mass.unit == "kg"
