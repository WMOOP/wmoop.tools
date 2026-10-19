"""Generators: emit idiomatic, correct and deterministic code from a WorldModel."""

from __future__ import annotations

import filecmp

import pytest

from wmoop_tools.generators.csharp_gen import _ident, generate_csharp
from wmoop_tools.generators.python_gen import generate_python
from wmoop_tools.loader import load_model


def _files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def _assert_identical(a, b):
    assert _files(a) == _files(b)
    for rel in _files(a):
        assert filecmp.cmp(a / rel, b / rel, shallow=False), f"non-deterministic: {rel}"


# --- Python binding ------------------------------------------------------------


def test_python_modules_emitted(generated_python):
    for mod in ("base", "animals", "society"):
        assert hasattr(generated_python, mod), f"missing generated module {mod}"


def test_python_inheritance_chain(generated_python):
    a = generated_python.animals
    assert issubclass(a.Person, a.Mammal)
    assert issubclass(a.Mammal, a.Animal)
    assert issubclass(a.Animal, generated_python.base.Thing)


def test_python_abstract_cannot_be_instantiated(generated_python):
    a = generated_python.animals
    with pytest.raises(TypeError):
        a.Animal("wm:x", "x")


def test_python_concrete_carries_properties(generated_python):
    a = generated_python.animals
    person = a.Person("wm:p", "Ada", label="person", legCount=2, fullName="Ada Lovelace")
    assert person.fullName == "Ada Lovelace"
    assert person.legCount == 2
    assert person.name == "Ada"


def test_python_role_attached_by_composition(generated_python):
    a, s = generated_python.animals, generated_python.society
    person = a.Person("wm:p", "Ada", fullName="Ada")
    citizen = s.Citizen(citizenId="RO-1")
    person.add_role(citizen)
    assert person.has_role(s.Citizen)
    assert person.get_role(s.Citizen).citizenId == "RO-1"
    assert citizen.subject is person
    # A role is NOT a subclass of its subject.
    assert not issubclass(s.Citizen, a.Person)
    assert s.Citizen.WM_PLAYED_BY == "wmoop.animals/Person"


def test_python_generation_is_deterministic(world_model, tmp_path):
    d1, d2 = tmp_path / "a", tmp_path / "b"
    generate_python(world_model, str(d1))
    generate_python(world_model, str(d2))
    _assert_identical(d1 / "wmoop_model", d2 / "wmoop_model")


# --- C# binding ----------------------------------------------------------------


def test_csharp_project_and_sources_emitted(world_model, tmp_path):
    out = tmp_path / "cs"
    generate_csharp(world_model, str(out))
    proj = out / "Wmoop.Generated"
    assert (proj / "Wmoop.Generated.csproj").is_file()
    cs_names = sorted(p.name for p in proj.rglob("*.cs"))
    assert "Animals.cs" in cs_names
    assert "_Runtime.cs" in cs_names


def test_csharp_generation_is_deterministic(world_model, tmp_path):
    d1, d2 = tmp_path / "a", tmp_path / "b"
    generate_csharp(world_model, str(d1))
    generate_csharp(world_model, str(d2))
    _assert_identical(d1 / "Wmoop.Generated", d2 / "Wmoop.Generated")


def test_csharp_ident_escapes_reserved_keywords():
    assert _ident("ref") == "@ref"
    assert _ident("class") == "@class"
    assert _ident("fullName") == "fullName"  # not a keyword -> unchanged


def test_csharp_keyword_property_emits_valid_identifier(tmp_path):
    # A property whose name is a C# keyword (`ref`) must be emitted as `@ref`
    # in the constructor signature and body, never as a bare `ref`.
    model = tmp_path / "model" / "cite"
    model.mkdir(parents=True)
    (model / "cite.wml.yaml").write_text(
        "module:\n  id: wmoop.cite\n  version: 1.0.0\n"
        "concepts:\n"
        "  - id: wmoop.cite/Citation\n"
        "    name: Citation\n"
        "    kind: concrete\n"
        "    properties:\n"
        "      - {id: wmoop.cite/Citation#ref, name: ref, type: string, cardinality: '0..1'}\n",
        encoding="utf-8",
    )
    wm = load_model(str(tmp_path / "model"))
    out = tmp_path / "cs"
    generate_csharp(wm, str(out))
    src = (out / "Wmoop.Generated" / "Cite.cs").read_text(encoding="utf-8")
    assert "string @ref" in src
    assert "Ref = @ref;" in src
    assert "string ref," not in src and "string ref)" not in src
