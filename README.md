# wmoop.tools

**The WMOOP toolchain — the piece that makes every language binding a *generated* artifact.**

`wmoop.tools` reads the canonical **WML World Model** (the `model/` directory in
[`wmoop.doc`](https://github.com/WMOOP/wmoop.doc)), validates it, and generates idiomatic code in
multiple languages from that single source. This is the mechanical core of WMOOP's central promise:
**model the world once, replicate it everywhere** — no hand-maintained duplication across
`wmoop.net`, `wmoop.py`, `wmoop.java`, `wmoop.cpp`.

> The adversarial design review called the missing toolchain *"the project that does not yet exist."*
> This is the first working version of it.

## Pipeline

```
model/*.wml.yaml  ──load──▶  WorldModel  ──validate──▶  (ok)  ──generate──▶  Python / C# / …
   (wmoop.doc)                (in memory)   invariants 3 & 5      per-language bindings
```

1. **Load** (`loader.py`) — parse every `*.wml.yaml` under each module folder (a module may span
   several files) into a typed in-memory model.
2. **Validate** (`compile.py`) — enforce the structural invariants: `extends`/`played_by` resolve,
   the module dependency graph is **acyclic** (Inv. 5), inheritance is acyclic and **shallow**
   (≤ 6, Inv. 3).
3. **Generate** (`generators/`) — emit idiomatic source per target.

### What is generated — and what is not

Generators emit **data only**: classes, properties, inheritance, enumerations, and roles. **Behaviour
is never generated** — algorithms like `can_drive`, `describe`, visitors, strategies and
specifications are hand-written extensions. This is the *generation gap* from
[PATTERNS.md](https://github.com/WMOOP/wmoop.doc/blob/main/PATTERNS.md): regenerating the model never
clobbers hand-written behaviour.

A nice touch the generator infers from the model: any concept that is the `played_by` target of a
role (e.g. `Person`) is emitted as **role-bearing** (composition), so roles attach correctly —
`Person` gets roles, `Driver` is never a subclass of `Person`.

## Usage

Requires **Python 3.10+** and **PyYAML** (`pip install -r requirements.txt`). Generating C# and
building it additionally needs the **.NET SDK**.

```bash
# Generate the Python binding from the canonical model
python -m wmoop_tools --model ../wmoop.doc/model --lang python --out build/py

# Generate the C# binding from the SAME model
python -m wmoop_tools --model ../wmoop.doc/model --lang csharp --out build/cs
```

(On Windows the launcher is usually `py`.)

## Conformance test

`tests/test_conformance.py` runs the whole pipeline on the real model, imports the generated Python,
and asserts the generated classes behave correctly — correct inheritance, abstract enforcement, the
biology chain, the geography Composite, and the cross-domain `Person`→`Driver` role attached by
composition.

```bash
python tests/test_conformance.py     # non-zero exit on failure
```

## Layout

```
wmoop.tools/
├── wmoop_tools/
│   ├── loader.py          # WML (*.wml.yaml) -> WorldModel
│   ├── model.py           # the in-memory model (dataclasses)
│   ├── compile.py         # validation + helpers (chains, topo-sort)
│   ├── cli.py             # `python -m wmoop_tools ...`
│   └── generators/
│       ├── python_gen.py  # -> idiomatic Python (dataclasses, ABCs, mixin)
│       └── csharp_gen.py  # -> idiomatic C# (structs, abstract classes, IHasRoles)
├── tests/test_conformance.py
└── requirements.txt
```

## Roadmap

- More targets: Java, C++.
- A canonical compiled form (`wm.json`, JCS-normalized) + content hashing, per the architecture spec.
- A language-neutral **conformance suite** (golden cases) every binding must pass.
- Richer validation: provenance presence, naming rules, unit/dimension checks.

## License

**Apache-2.0**.
