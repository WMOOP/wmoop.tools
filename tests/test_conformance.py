"""Conformance test: parse the real WML model, generate Python, import it, verify.

Proves the pipeline end to end — WML -> compiled model -> generated code -> working
classes — against the same cross-domain example the hand-written bindings use.
"""
import importlib
import os
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)                       # the wmoop.tools repo
sys.path.insert(0, ROOT)

MODEL = os.path.abspath(os.path.join(ROOT, "..", "wmoop.doc", "model"))
OUT = os.path.join(ROOT, "build", "py")

_fail = 0


def check(label, ok):
    global _fail
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        _fail += 1


def raises(exc, fn):
    try:
        fn()
        return False
    except exc:
        return True


from wmoop_tools.compile import validate           # noqa: E402
from wmoop_tools.generators.python_gen import generate_python  # noqa: E402
from wmoop_tools.loader import load_model          # noqa: E402

if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT, exist_ok=True)

wm = validate(load_model(MODEL))
generate_python(wm, OUT)
check("WML model loads and validates (>= 3 modules)", len(wm.modules) >= 3)

sys.path.insert(0, OUT)
transport = importlib.import_module("wmoop_model.transport")
nature = importlib.import_module("wmoop_model.nature")
geography = importlib.import_module("wmoop_model.geography")
runtime = importlib.import_module("wmoop_model._runtime")

Vehicle, RoadVehicle, Motorcycle, Moped = transport.Vehicle, transport.RoadVehicle, transport.Motorcycle, transport.Moped
Driver = transport.Driver
Person, Human, Animal = nature.Person, nature.Human, nature.Animal
Quantity = runtime.Quantity

check("Generated inheritance: Moped -> Motorcycle -> RoadVehicle -> Vehicle",
      issubclass(Moped, Motorcycle) and issubclass(Motorcycle, RoadVehicle) and issubclass(RoadVehicle, Vehicle))
check("Abstract concepts cannot be instantiated (Vehicle)",
      raises(TypeError, lambda: Vehicle("wm:x", "x")))

moped = Moped("wm:transport/moped/x", "Ciao", wheelCount=2,
              maxSpeed=Quantity(45, "km/h"), engineDisplacement=Quantity(49, "cc"))
check("Generated Moped instantiates and carries typed properties",
      moped.wheelCount == 2 and str(moped.maxSpeed) == "45 km/h" and str(moped.engineDisplacement) == "49 cc")

check("Generated biology chain: Person -> Human -> Animal",
      issubclass(Person, Human) and issubclass(Human, Animal))
check("Driver role records played_by = Person (from WML)",
      getattr(Driver, "WM_PLAYED_BY", "") == "wmoop.nature/Person")
check("Generated geography: Country/County/City are AdministrativeArea",
      issubclass(geography.Country, geography.AdministrativeArea)
      and issubclass(geography.City, geography.AdministrativeArea))

# Cross-domain role attachment on GENERATED classes (composition, not inheritance).
ada = Person("wm:nature/person/ada", "Ada", legCount=2, fullName="Ada Lovelace", dateOfBirth=None)
drv = Driver(licenceNumber="RO-AB-1", licenceCategories=["AM", "B"], licenceExpiry=None)
ada.add_role(drv)
check("Generated Person can hold a Driver role by composition",
      ada.has_role(Driver) and ada.get_role(Driver).licenceNumber == "RO-AB-1")
check("Role is bound back to its subject", drv.subject is ada)
check("A Driver is NOT a subclass of Person (role, not inheritance)",
      not issubclass(Driver, Person))

print(f"\n{'all conformance checks passed' if _fail == 0 else str(_fail) + ' check(s) FAILED'}")
sys.exit(0 if _fail == 0 else 1)
