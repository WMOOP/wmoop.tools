"""Conformance test: parse the real WML model, generate Python, import it, verify.

Proves the pipeline end to end — WML -> compiled model -> generated code -> working
classes — against the same cross-domain example the hand-written bindings use.

This is an *integration* test: it needs the canonical model from the external
``wmoop.doc`` repository. It is skipped automatically when that model is not present.

Set the model location with the ``WMOOP_MODEL`` environment variable, or check out
``wmoop.doc`` next to this repository so ``../wmoop.doc/model`` exists.

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
    default = ROOT.parent / "wmoop.doc" / "model"
    return default.resolve() if default.is_dir() else None


def _forget_generated() -> None:
    for name in list(sys.modules):
        if name == "wmoop_model" or name.startswith("wmoop_model."):
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

    transport = importlib.import_module("wmoop_model.transport")
    nature = importlib.import_module("wmoop_model.nature")
    geography = importlib.import_module("wmoop_model.geography")
    runtime = importlib.import_module("wmoop_model._runtime")
    return wm, transport, nature, geography, runtime


def _raises(exc, fn) -> bool:
    try:
        fn()
        return False
    except exc:
        return True


def checks(wm, transport, nature, geography, runtime) -> list[tuple[str, bool]]:
    """Return a list of (label, passed) for every conformance assertion."""
    Vehicle, RoadVehicle, Motorcycle, Moped = (
        transport.Vehicle,
        transport.RoadVehicle,
        transport.Motorcycle,
        transport.Moped,
    )
    Driver = transport.Driver
    Person, Human, Animal = nature.Person, nature.Human, nature.Animal
    Quantity = runtime.Quantity

    results: list[tuple[str, bool]] = []
    results.append(("WML model loads and validates (>= 3 modules)", len(wm.modules) >= 3))
    results.append(
        (
            "Generated inheritance: Moped -> Motorcycle -> RoadVehicle -> Vehicle",
            issubclass(Moped, Motorcycle) and issubclass(Motorcycle, RoadVehicle) and issubclass(RoadVehicle, Vehicle),
        )
    )
    results.append(
        ("Abstract concepts cannot be instantiated (Vehicle)", _raises(TypeError, lambda: Vehicle("wm:x", "x")))
    )

    moped = Moped(
        "wm:transport/moped/x",
        "Ciao",
        wheelCount=2,
        maxSpeed=Quantity(45, "km/h"),
        engineDisplacement=Quantity(49, "cc"),
    )
    results.append(
        (
            "Generated Moped instantiates and carries typed properties",
            moped.wheelCount == 2 and str(moped.maxSpeed) == "45 km/h" and str(moped.engineDisplacement) == "49 cc",
        )
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

    ada = Person("wm:nature/person/ada", "Ada", legCount=2, fullName="Ada Lovelace", dateOfBirth=None)
    drv = Driver(licenceNumber="RO-AB-1", licenceCategories=["AM", "B"], licenceExpiry=None)
    ada.add_role(drv)
    results.append(
        (
            "Generated Person can hold a Driver role by composition",
            ada.has_role(Driver) and ada.get_role(Driver).licenceNumber == "RO-AB-1",
        )
    )
    results.append(("Role is bound back to its subject", drv.subject is ada))
    results.append(("A Driver is NOT a subclass of Person (role, not inheritance)", not issubclass(Driver, Person)))
    return results


def test_conformance():
    """Pytest entry point — skips when the canonical model is unavailable."""
    import pytest

    model = model_dir()
    if model is None:
        pytest.skip("canonical wmoop.doc model not found (set WMOOP_MODEL or check out ../wmoop.doc)")

    out = ROOT / "build" / "py"
    results = checks(*build(model, out))
    failed = [label for label, ok in results if not ok]
    assert not failed, "conformance failures:\n  - " + "\n  - ".join(failed)


def _main() -> int:
    model = model_dir()
    if model is None:
        print("SKIP: canonical wmoop.doc model not found (set WMOOP_MODEL or check out ../wmoop.doc)")
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
