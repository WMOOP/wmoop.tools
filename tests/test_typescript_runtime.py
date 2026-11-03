"""The generated TypeScript compiles under its own strict tsconfig.json, and behaves at runtime.

The tests compile the generated modules with ``tsc``, then run small ES modules against the output
with Node.js. They need both: ``tsc`` on the PATH (or its path in ``WMOOP_TSC``) and ``node``, and
skip without them. CI's TypeScript job installs both.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from wmoop_tools.compile import validate
from wmoop_tools.generators.typescript_gen import generate_typescript
from wmoop_tools.loader import load_model

TSC = os.environ.get("WMOOP_TSC") or shutil.which("tsc")
NODE = shutil.which("node")
MODEL = Path(__file__).resolve().parent.parent / "external" / "wmoop.doc" / "model"

pytestmark = [
    pytest.mark.typescript,
    pytest.mark.skipif(not (TSC and NODE), reason="needs tsc (or WMOOP_TSC) and node"),
]

_FIXTURE_MODULES = ("_kernel", "core", "base", "animals", "society")

# Helpers every script starts with: the registry code of what a call throws, and a strict assertion.
_HELPERS = """
const code = (fn) => {
  try {
    fn();
    return "no error";
  } catch (e) {
    return e instanceof core.WmoopError ? e.code : `uncoded ${e?.constructor?.name}: ${e?.message}`;
  }
};
const results = [];
const check = (label, ok) => results.push([label, ok === true]);
"""


def compile_typescript(wm, root: Path) -> Path:
    """Generate ``wm`` into ``root/gen``, check it with its own tsconfig.json, emit it into ``root/js``."""
    gen, js = root / "gen", root / "js"
    generate_typescript(wm, str(gen))
    assert TSC is not None
    for extra in ([], ["--noEmit", "false", "--rootDir", str(gen), "--outDir", str(js)]):
        proc = subprocess.run([TSC, "-p", str(gen), *extra], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    shutil.copy(gen / "package.json", js / "package.json")
    return js


def run(js: Path, body: str, modules=_FIXTURE_MODULES) -> dict[str, bool]:
    """Run ``body`` as an ES module, with each module imported under its name (``_kernel`` as ``kernel``)."""
    imports = [
        f"const {m.lstrip('_')} = await import({json.dumps((js / 'wmoop' / f'{m}.js').as_uri())});" for m in modules
    ]
    script = js / "case.mjs"
    script.write_text("\n".join([*imports, _HELPERS, body, "console.log(JSON.stringify(results));"]), encoding="utf-8")
    assert NODE is not None
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    results = json.loads(proc.stdout.strip().splitlines()[-1])
    return dict(results)


def assert_all(results: dict[str, bool]) -> None:
    failed = [label for label, ok in results.items() if not ok]
    assert not failed, f"failed: {failed}"


@pytest.fixture(scope="module")
def js(tmp_path_factory, world_model) -> Path:
    return compile_typescript(world_model, tmp_path_factory.mktemp("ts"))


def test_errors_carry_their_registry_code(js):
    assert_all(
        run(
            js,
            """
const person = (init = {}) => new animals.Person({ id: "wm:p", name: "Ada", label: "p", fullName: "Ada", ...init });
class Rock extends base.Thing {}  // hand-written, so instantiable
const attachedTwice = () => {
  const citizen = new society.Citizen({ citizenId: "RO-1" });
  person({ id: "wm:p1" }).addRole(citizen);
  person({ id: "wm:p2" }).addRole(citizen);
};
check("id", code(() => new core.ConceptId(" ")) === "WM-ID-INVALID");
check("unit", code(() => new core.Quantity(1, "")) === "WM-UNIT-MISSING");
check("abstract", code(() => new animals.Animal({ id: "wm:x", name: "x", label: "x" })) === "WM-ABSTRACT-INSTANTIATION");
check("name", code(() => person({ name: " " })) === "WM-REQUIRED-MISSING");
check("required", code(() => person({ fullName: undefined })) === "WM-REQUIRED-MISSING");
check("enum", code(() => person({ sex: "unknown" })) === "WM-TYPE-MISMATCH");
check("attached", code(attachedTwice) === "WM-ROLE-ALREADY-ATTACHED");
check("player", code(() => new Rock({ id: "wm:r", name: "r", label: "r" }).addRole(new society.Citizen({ citizenId: "RO-1" }))) === "WM-ROLE-PLAYER-MISMATCH");
check("target", code(() => person().knows.add("Bob")) === "WM-RELATION-TARGET-TYPE");
check("error", new core.WmoopError("WM-ID-INVALID", "x") instanceof Error);
""",
        )
    )


def test_roles_are_attached_by_composition(js):
    assert_all(
        run(
            js,
            """
const ada = new animals.Person({ id: "wm:p", name: "Ada", label: "p", fullName: "Ada" });
const citizen = new society.Citizen({ citizenId: "RO-1" });
check("returns the role", ada.addRole(citizen) === citizen);
check("has", ada.hasRole(society.Citizen) && ada.getRole(society.Citizen).citizenId === "RO-1");
check("subject", citizen.subject === ada && String(citizen.roleType) === "wmoop.society/Citizen");
check("not a subclass", !(citizen instanceof animals.Person));
check("roles", ada.roles.length === 1 && Object.isFrozen(ada.roles));
const second = new society.Citizen({ citizenId: "RO-2" });
check("per player", code(() => ada.addRole(second)) === "WM-ROLE-DUPLICATE" && second.subject === null);
const bob = new animals.Person({ id: "wm:b", name: "Bob", label: "p", fullName: "Bob" });
check("another player", bob.addRole(second).subject === bob);
check("is-a", ada.isA("wmoop.animals/Mammal") && ada.isA("wmoop.base/Thing") && !ada.isA("wmoop.society/Citizen"));
""",
        )
    )


def test_relations_keep_their_inverse_in_step(js):
    assert_all(
        run(
            js,
            """
const thing = (id) => new animals.Person({ id, name: id, label: id, fullName: id });
const [whole, other, part] = [thing("w"), thing("o"), thing("p")];
part.partOf = whole;
check("to-one sets the inverse", [...whole.hasPart].length === 1 && whole.hasPart.has(part));
other.hasPart.add(part);  // adding on the to-many end moves the part
check("moved", part.partOf === other && whole.hasPart.size === 0 && other.hasPart.has(part));
check("delete", other.hasPart.delete(part) === true && part.partOf === null && other.hasPart.size === 0);
check("delete again", other.hasPart.delete(part) === false);
const [ada, bob] = [thing("a"), thing("b")];
ada.knows.add(bob);
check("many-to-many", bob.knownBy.has(ada) && ada.knows.has(bob));
bob.knownBy.delete(ada);
check("both sides", ada.knows.size === 0 && bob.knownBy.size === 0);
check("cannot be replaced", code(() => { ada.knows = []; }).startsWith("uncoded TypeError"));
const citizen = new society.Citizen({ citizenId: "RO-1" });
citizen.residesIn = whole;
check("cross-module forward end", citizen.residesIn === whole);
check("no cross-module inverse", !("residents" in base.Thing.prototype));
""",
        )
    )


def test_individuals_are_read_only_statics(js):
    assert_all(
        run(
            js,
            """
const ada = animals.Person.Ada;
check("instance", ada instanceof animals.Person && String(ada.id) === "wmoop.animals/Ada");
check("values", ada.name === "Ada Lovelace" && ada.fullName === "Augusta Ada King" && ada.legCount === 2);
check("enum and date", ada.sex === animals.Sex.female && ada.dateOfBirth.toISOString() === "1815-12-10T00:00:00.000Z");
check("quantity", ada.mass.equals(new core.Quantity(55, "kg")));
check("defaults apply", core.Unit.Gram.symbol === "g" && core.Unit.Gram.factor === 0.001 && core.Unit.Gram.offset === 0);
check("refers by id", core.QuantityKind.Mass.canonicalUnit === "wmoop.core/Kilogram");
check("read-only", code(() => { animals.Person.Ada = null; }).startsWith("uncoded TypeError"));
""",
        )
    )


def test_quantities_check_their_unit_and_convert_within_their_kind(js):
    assert_all(
        run(
            js,
            """
const Q = core.Quantity;
const person = (mass) => new animals.Person({ id: "wm:p", name: "P", label: "p", fullName: "P", mass });
check("any unit of the kind", person(new Q(55000, "g")).mass.equals(new Q(55000, "g")));
check("dimension", code(() => person(new Q(1.7, "m"))) === "WM-UNIT-DIMENSION-MISMATCH");
check("not in the catalogue", code(() => person(new Q(120, "lb"))) === "WM-UNIT-DIMENSION-MISMATCH");
check("not a quantity", code(() => person(55)) === "WM-TYPE-MISMATCH");
check("kind", code(() => kernel.checkQuantity(new Q(1, "rad"), "one", "wmoop.core/Count", "count")) === "WM-QUANTITYKIND-MISMATCH");
check("convert kind", code(() => new Q(1, "rad").in("one")) === "WM-QUANTITYKIND-MISMATCH");
check("g to kg", Math.abs(new Q(55000, "g").in("kg") - 55) < 1e-9);
check("degC to K", Math.abs(new Q(20, "degC").in("K") - 293.15) < 1e-9);
check("K to degC", Math.abs(new Q(300, "K").in("degC") - 26.85) < 1e-9);
check("text", String(new Q(5.97e24, "kg")) === "5.97e+24 kg" && String(new Q(45, "km/h")) === "45 km/h");
check("value equality", new Q(49, "cm3").equals(new Q(49, "cm3")) && !new Q(49, "cm3").equals(new Q(49, "km/h")));
check("frozen", Object.isFrozen(new Q(1, "kg")) && Object.isFrozen(new core.ConceptId("x")));
""",
        )
    )


def test_simple_invariants_are_checked_in_the_constructor(js):
    assert_all(
        run(
            js,
            """
const person = (init) => new animals.Person({ id: "wm:p", name: "P", label: "p", fullName: "P", ...init });
check("own", code(() => person({ legCount: -1 })) === "WM-INVARIANT-FAILED");
check("narrowed", code(() => person({ legCount: 3 })) === "WM-INVARIANT-FAILED");
check("quantity", code(() => person({ mass: new core.Quantity(0, "g") })) === "WM-INVARIANT-FAILED");
check("absent breaks none", person({}).legCount === null);
""",
        )
    )


def test_extend_adds_behaviour_that_subclasses_inherit_and_refine(js):
    assert_all(
        run(
            js,
            """
core.extend(animals.Animal, {
  get legs() { return this.legCount ?? 0; },
  describe() { return `${this.name} has ${this.legs} legs`; },
});
core.extend(animals.Person, {
  describe() { return "person " + super.describe(); },
});
const ada = new animals.Person({ id: "wm:p", name: "Ada", label: "p", fullName: "Ada", legCount: 2 });
check("inherited and refined", ada.describe() === "person Ada has 2 legs");
check("getter", ada.legs === 2);
check("only adds", code(() => core.extend(animals.Person, { fullName: "x" })).startsWith("uncoded TypeError"));
""",
        )
    )


def test_names_that_clash_still_compile(tmp_path):
    """A type named like a global, a value that is not an identifier, a property named like a kernel member."""
    model = tmp_path / "model" / "cite"
    model.mkdir(parents=True)
    (model / "cite.wml.yaml").write_text(
        "module: {id: wmoop.cite, version: 1.0.0}\n"
        "enumerations:\n"
        "  - {id: wmoop.cite/Kind, values: [{id: default}, {id: A-1}]}\n"
        "concepts:\n"
        "  - id: wmoop.cite/Date\n"
        "    kind: concrete\n"
        "    properties:\n"
        "      - {id: wmoop.cite/Date#name, name: name, type: string}\n"
        "      - {id: wmoop.cite/Date#when, name: when, type: date}\n"
        "      - {id: wmoop.cite/Date#kinds, name: kinds, type: wmoop.cite/Kind, cardinality: '0..*'}\n"
        "      - {id: wmoop.cite/Date#kind, name: kind, type: wmoop.cite/Kind, default: A-1}\n"
        "individuals:\n"
        "  - {id: wmoop.cite/prototype, name: P, instance_of: wmoop.cite/Date, values: {name: x, when: 2020-01-02}}\n",
        encoding="utf-8",
    )
    js = compile_typescript(validate(load_model(str(tmp_path / "model"))), tmp_path)
    assert_all(
        run(
            js,
            """
const d = cite.Date.prototypeIndividual;
check("renamed", d instanceof cite.Date && d.nameValue === "x" && d.name === "P");
check("default", d.kind === "A-1" && d.kinds.length === 0);
check("date", d.when.toISOString() === "2020-01-02T00:00:00.000Z");
""",
            modules=("_kernel", "core", "cite"),
        )
    )


@pytest.mark.skipif(not MODEL.is_dir(), reason="external/wmoop.doc is not checked out")
def test_the_pinned_model_compiles_and_loads(tmp_path):
    """Every module of the real model compiles strictly and loads: its individuals are built, so checked."""
    wm = validate(load_model(str(MODEL)))
    js = compile_typescript(wm, tmp_path)
    modules = [
        "_kernel",
        "core",
        *sorted(p.stem for p in (js / "wmoop").glob("*.js") if p.stem not in ("_kernel", "core")),
    ]
    body = (
        "for (const [name, mod] of Object.entries({" + ", ".join(m.lstrip("_") for m in modules) + "})) {\n"
        "  check(name, Object.keys(mod).length > 0);\n"
        "}\n"
    )
    assert_all(run(js, body, modules=modules))
