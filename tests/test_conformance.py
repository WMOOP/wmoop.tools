"""Conformance test: parse the real WML model, generate Python, import it, verify.

Proves the pipeline end to end — WML -> compiled model -> generated code -> working
classes — against the same cross-domain example the hand-written bindings use.

This is an *integration* test: it needs the canonical model from the external
``wmoop.doc`` repository. It is skipped automatically when that model is not present.

The model is the pinned ``external/wmoop.doc`` submodule (``git submodule update --init``).
``WMOOP_MODEL`` overrides it, and a ``wmoop.doc`` checkout next to this repository
(``../wmoop.doc/model``) still works.

    python tests/test_conformance.py     # standalone: non-zero exit on failure
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent  # the wmoop.tools repo
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def model_dir() -> Path | None:
    """Locate the canonical model, or ``None`` if it is not available."""
    env = os.environ.get("WMOOP_MODEL")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    # The pinned submodule first; a sibling checkout (../wmoop.doc) still works for local hacking.
    for default in (ROOT / "external" / "wmoop.doc" / "model", ROOT.parent / "wmoop.doc" / "model"):
        if default.is_dir() and any(default.iterdir()):
            return default.resolve()
    return None


def _forget_generated() -> None:
    for name in list(sys.modules):
        if name.split(".")[0] in ("wmoop", "wmoop_ext"):
            del sys.modules[name]


def build(model: Path, out: Path):
    """Run the pipeline and import the generated package. Returns a namespace dict."""
    from wmoop_tools.compile import validate
    from wmoop_tools.generators.python_gen import generate_python
    from wmoop_tools.loader import load_model

    if out.is_dir():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    wm = validate(load_model(str(model)))
    generate_python(wm, str(out))

    _forget_generated()
    if str(out) not in sys.path:
        sys.path.insert(0, str(out))
    importlib.invalidate_caches()

    transport = importlib.import_module("wmoop.transport")
    nature = importlib.import_module("wmoop.nature")
    geography = importlib.import_module("wmoop.geography")
    core = importlib.import_module("wmoop.core")
    return wm, transport, nature, geography, core


def _raises(exc, fn) -> bool:
    try:
        fn()
        return False
    except exc:
        return True


def checks(wm, transport, nature, geography, core) -> list[tuple[str, bool]]:
    """Return a list of (label, passed) for every conformance assertion."""
    Vehicle, RoadVehicle, Motorcycle, Moped = (
        transport.Vehicle,
        transport.RoadVehicle,
        transport.Motorcycle,
        transport.Moped,
    )
    Driver = transport.Driver
    Person, Human, Animal = nature.Person, nature.Human, nature.Animal
    Quantity = core.Quantity

    results: list[tuple[str, bool]] = []
    results.append(("WML model loads and validates (>= 3 modules)", len(wm.modules) >= 3))
    results.append(
        (
            "Generated inheritance: Moped -> Motorcycle -> RoadVehicle -> Vehicle",
            issubclass(Moped, Motorcycle) and issubclass(Motorcycle, RoadVehicle) and issubclass(RoadVehicle, Vehicle),
        )
    )
    results.append(
        (
            "Abstract concepts cannot be instantiated (Vehicle)",
            _raises(TypeError, lambda: Vehicle("wm:x", "x", wheel_count=4)),
        )
    )

    moped = Moped(
        "wm:transport/moped/x",
        "Ciao",
        wheel_count=2,
        max_speed=Quantity(45, "km/h"),
        engine_displacement=Quantity(49, "cm3"),
    )
    results.append(
        (
            "Generated Moped instantiates and carries typed properties",
            moped.wheel_count == 2 and str(moped.max_speed) == "45 km/h" and str(moped.engine_displacement) == "49 cm3",
        )
    )
    results.append(("A default from the model applies (RoadVehicle#roadLegal)", moped.road_legal is True))
    results.append(
        ("A required slot cannot be left out (Vehicle#wheelCount)", _raises(TypeError, lambda: Moped("wm:x", "x")))
    )
    results.append(
        (
            "Generated biology chain: Person -> Human -> Animal",
            issubclass(Person, Human) and issubclass(Human, Animal),
        )
    )
    results.append(
        (
            "Driver role records played_by = Person (from WML)",
            getattr(Driver, "WM_PLAYED_BY", "") == "wmoop.nature/Person",
        )
    )
    results.append(
        (
            "Generated geography: Country/City are AdministrativeArea",
            issubclass(geography.Country, geography.AdministrativeArea)
            and issubclass(geography.City, geography.AdministrativeArea),
        )
    )

    ada = Person("wm:nature/person/ada", "Ada", leg_count=2, full_name="Ada Lovelace")
    drv = Driver(licence_number="RO-AB-1", licence_categories=["AM", "B"])
    ada.add_role(drv)
    results.append(
        (
            "Generated Person can hold a Driver role by composition",
            ada.has_role(Driver) and ada.get_role(Driver).licence_number == "RO-AB-1",
        )
    )
    results.append(("Role is bound back to its subject", drv.subject is ada))
    results.append(("A Driver is NOT a subclass of Person (role, not inheritance)", not issubclass(Driver, Person)))
    results.append(
        (
            "A role refuses a subject that is not its played_by type (Driver on a Moped)",
            _raises(TypeError, lambda: moped.add_role(Driver(licence_number="X", licence_categories=["B"]))),
        )
    )
    results.append(
        (
            "Absent optional slots read as None, not as a value (Driver#licenceExpiry)",
            drv.licence_expiry is None and ada.date_of_birth is None,
        )
    )
    results.append(
        (
            "Licence categories are the model's enumeration",
            drv.licence_categories == (transport.LicenceCategory.AM, transport.LicenceCategory.B),
        )
    )

    ro = geography.Country("wm:geo/RO", "Romania")
    cj = geography.County("wm:geo/CJ", "Cluj")
    cn = geography.City("wm:geo/CN", "Cluj-Napoca")
    cj.part_of = ro
    ro.contains.add(cn)
    cn.part_of = cj  # moves the city from the country into the county
    results.append(
        (
            "Generated composite: partOf and its inverse contains stay in step",
            list(ro.contains) == [cj] and list(cj.contains) == [cn] and cn.part_of is cj,
        )
    )
    owner = ada.add_role(transport.Owner())
    owner.owns.add(moped)
    results.append(
        (
            "Generated many-to-many relation: Owner.owns <-> Vehicle.ownedBy",
            list(moped.owned_by) == [owner] and list(owner.owns) == [moped],
        )
    )
    results.append(
        (
            "cardinality_per_player: a Person holds at most one Driver, any number of Owner roles",
            _raises(RuntimeError, lambda: ada.add_role(Driver(licence_number="RO-AB-2", licence_categories=["B"])))
            and ada.add_role(transport.Owner()).subject is ada,
        )
    )

    def moped_with(**values):
        return Moped("wm:x", "x", **({"wheel_count": 2, "engine_displacement": Quantity(49, "cm3")} | values))

    results.append(
        (
            "A quantity takes any unit of its kind (maxSpeed in m/s for a property in km/h)",
            abs(moped_with(max_speed=Quantity(12.5, "m/s")).max_speed.in_("km/h") - 45) < 1e-9,
        )
    )
    results.append(
        (
            "A quantity refuses a unit of another kind (maxSpeed in kg, engineDisplacement in km/h)",
            _raises(ValueError, lambda: moped_with(max_speed=Quantity(45, "kg")))
            and _raises(ValueError, lambda: moped_with(engine_displacement=Quantity(49, "km/h"))),
        )
    )
    results.append(
        (
            "A simple invariant is checked in the constructor (Vehicle wheels-nonneg)",
            _raises(ValueError, lambda: moped_with(wheel_count=-1)),
        )
    )
    space = importlib.import_module("wmoop.space")
    results.append(
        (
            "Individuals are generated: the Earth, with the model's values in their units",
            isinstance(space.Planet.Earth, space.Planet)
            and abs(space.Planet.Earth.equatorial_radius.in_("m") - 6378100) < 1e-6
            and core.Unit.KilometrePerHour.quantity_kind == "wmoop.core/Speed",
        )
    )
    missing = [i.id for i in wm.individuals.values() if not _generated(i)]
    results.append((f"Every individual of the model is generated ({len(wm.individuals)})", not missing))
    return results


def _generated(individual) -> bool:
    """The individual is an instance of its class, held on that class under its local name."""
    module = importlib.import_module("wmoop." + individual.module.partition(".")[2])
    cls = getattr(module, individual.instance_of.rpartition("/")[2])
    held = getattr(cls, individual.id.rpartition("/")[2], None)
    return isinstance(held, cls) and str(held.id) == individual.id


def test_conformance():
    """Pytest entry point — skips when the canonical model is unavailable."""
    import pytest

    model = model_dir()
    if model is None:
        pytest.skip("canonical wmoop.doc model not found (run: git submodule update --init, or set WMOOP_MODEL)")

    out = ROOT / "build" / "py"
    results = checks(*build(model, out))
    failed = [label for label, ok in results if not ok]
    assert not failed, "conformance failures:\n  - " + "\n  - ".join(failed)


def _main() -> int:
    model = model_dir()
    if model is None:
        print("SKIP: canonical wmoop.doc model not found (run: git submodule update --init, or set WMOOP_MODEL)")
        return 0
    out = ROOT / "build" / "py"
    results = checks(*build(model, out))
    fail = 0
    for label, ok in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fail += 1
    print(f"\n{'all conformance checks passed' if fail == 0 else str(fail) + ' check(s) FAILED'}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(_main())
