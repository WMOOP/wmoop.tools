"""Loader: WML (*.wml.yaml) folders -> WorldModel."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from wmoop_tools.cli import main as cli_main
from wmoop_tools.compile import ModelError
from wmoop_tools.loader import load_model

NESTED_MODEL = Path(__file__).parent / "fixtures" / "nested_model"
WIDGETS_MODULE = (
    "module:\n  id: wmoop.widgets\n  version: 1.0.0\nconcepts:\n  - {id: wmoop.widgets/Widget, kind: concrete}\n"
)
GEAR = "concepts:\n  - {id: wmoop.widgets/Gear, kind: concrete}\n"


def _write(path: Path, text: str = GEAR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _nested_copy(tmp_path: Path) -> Path:
    model = tmp_path / "model"
    shutil.copytree(NESTED_MODEL, model)
    return model


def test_modules_loaded(world_model):
    assert set(world_model.modules) == {"wmoop.core", "wmoop.base", "wmoop.animals", "wmoop.society"}


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


def test_nested_model_file_is_an_error():
    # widgets/parts/parts.wml.yaml passes wmoop.doc's recursive validator, so skipping it
    # would drop wmoop.widgets/Gear from every binding without a word.
    with pytest.raises(ModelError) as raised:
        load_model(str(NESTED_MODEL))
    message = str(raised.value)
    assert message.startswith(f"Cannot assign 1 model file(s) under {NESTED_MODEL} to a module:")
    assert "  - widgets/parts/parts.wml.yaml: nested model folders are not supported yet" in message
    assert "subfolder of module folder 'widgets/'" in message
    assert "ADR 0004 (wmoop.doc, governance/adr/0004-model-folders-and-sub-modules.md)" in message


def test_nested_file_without_a_top_level_file_is_an_error(tmp_path):
    # A module folder that holds model files only in subfolders used to be skipped whole.
    _write(tmp_path / "law" / "criminal" / "criminal.wml.yaml")
    with pytest.raises(ModelError, match=r"law/criminal/criminal\.wml\.yaml: nested model folders"):
        load_model(str(tmp_path))


def test_every_unassigned_file_is_named(tmp_path):
    model = _nested_copy(tmp_path)
    _write(model / "widgets" / "parts" / "springs.wml.yaml")
    _write(model / "widgets" / "parts" / "small" / "pins.wml.yaml")
    _write(model / "stray.wml.yaml")
    with pytest.raises(ModelError) as raised:
        load_model(str(model))
    lines = str(raised.value).splitlines()
    assert lines[0].startswith("Cannot assign 4 model file(s) under")
    assert [line.split(":")[0] for line in lines[1:5]] == [
        "  - stray.wml.yaml",
        "  - widgets/parts/parts.wml.yaml",
        "  - widgets/parts/small/pins.wml.yaml",
        "  - widgets/parts/springs.wml.yaml",
    ]
    assert lines[1] == "  - stray.wml.yaml: the file is not inside a module folder"
    assert "ADR 0004" in lines[-1]


def test_underscore_and_dot_dirs_are_skipped_at_any_depth(tmp_path):
    model = _nested_copy(tmp_path)
    (model / "widgets" / "parts").rename(model / "widgets" / "_parts")
    _write(model / "widgets" / ".cache" / "parts.wml.yaml")
    _write(model / "widgets" / "_drafts" / "deeper" / "gear.wml.yaml")
    _write(model / "_template" / "sub" / "x.wml.yaml")

    wm = load_model(str(model))
    assert set(wm.modules) == {"wmoop.widgets"}
    assert set(wm.concepts) == {"wmoop.widgets/Widget"}


def test_files_that_are_not_model_files_are_ignored(tmp_path):
    # wmoop.doc's model/ holds README.md and taxonomy.yaml at its root; a module folder may
    # hold notes. Only *.wml.yaml files count.
    _write(tmp_path / "widgets" / "widgets.wml.yaml", WIDGETS_MODULE)
    _write(tmp_path / "README.md", "# Model\n")
    _write(tmp_path / "taxonomy.yaml", "clusters: []\n")
    _write(tmp_path / "widgets" / "notes" / "README.md", "# Notes\n")
    _write(tmp_path / "widgets" / "notes" / "gear.yaml")

    wm = load_model(str(tmp_path))
    assert set(wm.modules) == {"wmoop.widgets"}


def test_cli_reports_a_nested_model_file(capsys):
    assert cli_main(["--model", str(NESTED_MODEL), "--check"]) == 2
    err = capsys.readouterr().err
    assert "widgets/parts/parts.wml.yaml: nested model folders are not supported yet" in err
    assert "ADR 0004" in err


def test_module_metadata(world_model):
    animals = world_model.modules["wmoop.animals"]
    assert animals.version == "1.0.0"
    assert animals.title == "Animals"
    assert animals.dir_name == "animals"


def test_depends_on_parsed(world_model):
    assert world_model.modules["wmoop.animals"].depends_on == ["wmoop.core", "wmoop.base"]
    assert world_model.modules["wmoop.society"].depends_on == ["wmoop.animals", "wmoop.base"]


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


def test_relations_are_loaded(world_model):
    thing = world_model.concepts["wmoop.base/Thing"]
    (part_of,) = thing.relations
    assert (part_of.name, part_of.target, part_of.cardinality, part_of.rel) == (
        "partOf",
        "wmoop.base/Thing",
        "0..1",
        "part_of",
    )
    assert part_of.inverse == "wmoop.base/Thing#hasPart"
    citizen = world_model.roles["wmoop.society/Citizen"]
    assert [r.name for r in citizen.relations] == ["residesIn"]


def test_individuals_are_loaded(world_model):
    ada = world_model.individuals["wmoop.animals/Ada"]
    assert (ada.name, ada.instance_of, ada.module) == ("Ada Lovelace", "wmoop.animals/Person", "wmoop.animals")
    assert ada.values["legCount"] == 2 and ada.values["sex"] == "female"
    core = world_model.modules["wmoop.core"]
    assert [i.id for i in core.individuals][:3] == ["wmoop.core/Mass", "wmoop.core/Length", "wmoop.core/Temperature"]
    assert world_model.individuals["wmoop.core/Gram"].values == {
        "symbol": "g",
        "quantityKind": "wmoop.core/Mass",
        "factor": 0.001,
    }


def test_invariants_and_cardinality_per_player_are_loaded(world_model):
    animal = world_model.concepts["wmoop.animals/Animal"]
    assert [(i.id, i.expr) for i in animal.invariants] == [
        ("legs-nonneg", "self.legCount >= 0"),
        ("positive-mass", "self.mass > 0"),
    ]
    assert animal.invariants[0].message == "An animal cannot have a negative number of legs."
    assert animal.invariants[1].message is None
    assert world_model.roles["wmoop.society/Citizen"].cardinality_per_player == "0..1"
