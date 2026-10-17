"""Generators: emit idiomatic, correct and deterministic code from a WorldModel."""

from __future__ import annotations

import filecmp

import pytest

from wmoop_tools.generators.csharp_gen import generate_csharp
from wmoop_tools.generators.python_gen import generate_python


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
