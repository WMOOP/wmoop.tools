"""Loader: WML (*.wml.yaml) folders -> WorldModel."""

from __future__ import annotations

from wmoop_tools.loader import load_model


def test_modules_loaded(world_model):
    assert set(world_model.modules) == {"wmoop.base", "wmoop.animals", "wmoop.society"}


def test_underscore_and_dot_dirs_are_skipped(tmp_path):
    # Real module.
    real = tmp_path / "widgets"
    real.mkdir()
    (real / "widgets.wml.yaml").write_text(
        "module:\n  id: wmoop.widgets\n  version: 1.0.0\n"
        "concepts:\n  - {id: wmoop.widgets/Widget, name: Widget, kind: concrete}\n",
        encoding="utf-8",
    )
    # Scaffolding/tooling dirs the loader must ignore: a leading "_" (e.g. the
    # DOMAIN template, whose placeholder YAML would emit uncompilable source) or ".".
    for skipped in ("_template", ".hidden"):
        d = tmp_path / skipped
        d.mkdir()
        (d / "x.wml.yaml").write_text(
            "module:\n  id: wmoop.<id>\n  version: 0.1.0\n"
            "concepts:\n  - {id: wmoop.<id>/<Concept>, name: <Concept>, kind: abstract}\n",
            encoding="utf-8",
        )

    wm = load_model(str(tmp_path))
    assert set(wm.modules) == {"wmoop.widgets"}


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
