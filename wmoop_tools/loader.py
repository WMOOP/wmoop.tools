"""Parse WML (*.wml.yaml) files into a :class:`WorldModel`.

Each top-level folder under the model directory is one module; a module may be split
across several ``*.wml.yaml`` files (e.g. ``transport.wml.yaml`` + ``roles.wml.yaml``).

The loader reads the whole tree. A ``*.wml.yaml`` that is not directly inside a module
folder (one in a subfolder of a module, or one directly in the model directory) raises
:class:`ModelError` instead of being skipped: ``wmoop.doc``'s validator searches the tree
recursively, so a skipped file would pass validation and yet generate no code.
"""

from __future__ import annotations

import fnmatch
import os

import yaml

from .compile import ModelError
from .model import (
    Concept,
    Datatype,
    Enumeration,
    EnumValue,
    Individual,
    Invariant,
    Module,
    Property,
    Relation,
    Role,
    WorldModel,
)


def _prop(d: dict) -> Property:
    pid = d.get("id", "")
    return Property(
        id=pid,
        name=d.get("name") or pid.split("#")[-1],
        type=d.get("type"),
        unit=d.get("unit"),
        cardinality=str(d.get("cardinality", "0..1")),
        required=bool(d.get("required", False)),
        definition=d.get("definition"),
        default=d.get("default"),
    )


def _relation(d: dict) -> Relation:
    rid = d.get("id", "")
    return Relation(
        id=rid,
        name=d.get("name") or rid.split("#")[-1],
        target=d.get("target", ""),
        cardinality=str(d.get("cardinality", "0..*")),
        inverse=d.get("inverse"),
        rel=d.get("rel", "association"),
        definition=d.get("definition"),
    )


def _invariant(d: dict) -> Invariant:
    return Invariant(id=str(d.get("id", "")), expr=str(d.get("expr", "")), message=d.get("message"))


def _concept(d: dict, module_id: str) -> Concept:
    return Concept(
        id=d["id"],
        name=d.get("name", d["id"].split("/")[-1]),
        kind=d.get("kind", "concrete"),
        extends=d.get("extends"),
        implements=list(d.get("implements") or []),
        properties=[_prop(p) for p in (d.get("properties") or [])],
        relations=[_relation(r) for r in (d.get("relations") or [])],
        invariants=[_invariant(i) for i in (d.get("invariants") or [])],
        definition=d.get("definition"),
        module=module_id,
    )


def _role(d: dict, module_id: str) -> Role:
    return Role(
        id=d["id"],
        name=d.get("name", d["id"].split("/")[-1]),
        played_by=d.get("played_by"),
        context=d.get("context"),
        cardinality_per_player=str(d.get("cardinality_per_player", "0..*")),
        properties=[_prop(p) for p in (d.get("properties") or [])],
        relations=[_relation(r) for r in (d.get("relations") or [])],
        definition=d.get("definition"),
        module=module_id,
    )


def _enum(d: dict) -> Enumeration:
    return Enumeration(
        id=d["id"],
        name=d.get("name", d["id"].split("/")[-1]),
        values=[EnumValue(id=v["id"], definition=v.get("definition")) for v in (d.get("values") or [])],
        definition=d.get("definition"),
    )


def _datatype(d: dict) -> Datatype:
    return Datatype(
        id=d["id"],
        name=d.get("name", d["id"].split("/")[-1]),
        base=d.get("base"),
        definition=d.get("definition"),
    )


def _individual(d: dict) -> Individual:
    return Individual(
        id=d["id"],
        name=str(d.get("name", d["id"].split("/")[-1])),
        instance_of=d.get("instance_of", ""),
        values=dict(d.get("values") or {}),
        definition=d.get("definition"),
    )


MODEL_FILE_PATTERN = "*.wml.yaml"
ADR_0004 = "ADR 0004 (wmoop.doc, governance/adr/0004-model-folders-and-sub-modules.md)"


def _is_model_file(name: str) -> bool:
    # The same match as glob.glob(MODEL_FILE_PATTERN): hidden files are left out, and the
    # case is ignored where the file system ignores it.
    return not name.startswith(".") and fnmatch.fnmatch(name, MODEL_FILE_PATTERN)


def _raise(exc: OSError) -> None:
    # os.walk skips a directory it cannot read unless told otherwise; that would drop its files.
    raise exc


def _module_files(model_dir: str) -> dict[str, list[str]]:
    """Map each module folder name to the paths of its model files, in sorted order.

    Walks the whole tree under ``model_dir``. Only a file directly inside a top-level
    folder belongs to a module; any other model file raises :class:`ModelError`.
    """
    by_module: dict[str, list[str]] = {}
    unassigned: list[str] = []
    for dirpath, dirnames, filenames in os.walk(model_dir, onerror=_raise, followlinks=True):
        # A leading "_" or "." marks a directory that is not part of the model, at any
        # depth: scaffolding like "_template", or tooling dirs. Skip them so their
        # placeholder YAML never becomes a module; it would emit uncompilable source
        # (e.g. `class <Concept>`).
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(("_", ".")))
        files = sorted(f for f in filenames if _is_model_file(f))
        if not files:
            continue
        rel = os.path.relpath(dirpath, model_dir)
        parts = [] if rel == os.curdir else rel.split(os.sep)
        if len(parts) == 1:
            by_module[parts[0]] = [os.path.join(dirpath, f) for f in files]
        else:
            unassigned += ["/".join([*parts, f]) for f in files]
    if unassigned:
        raise ModelError(_unassigned_message(model_dir, sorted(unassigned)))
    return dict(sorted(by_module.items()))


def _unassigned_message(model_dir: str, files: list[str]) -> str:
    lines = [f"Cannot assign {len(files)} model file(s) under {model_dir} to a module:"]
    for f in files:
        if "/" in f:
            module_dir = f.split("/", 1)[0]
            lines.append(
                f"  - {f}: nested model folders are not supported yet "
                f"(the file is in a subfolder of module folder '{module_dir}/'; see ADR 0004)"
            )
        else:
            lines.append(f"  - {f}: the file is not inside a module folder")
    lines.append(
        "A model file must sit directly in its module's folder, <model>/<module>/*.wml.yaml; "
        "otherwise no binding generates code for it. Folders inside a module and sub-modules are "
        f"proposed in {ADR_0004} and wait for its ratification."
    )
    return "\n".join(lines)


def load_model(model_dir: str) -> WorldModel:
    wm = WorldModel()
    model_dir = os.path.abspath(model_dir)
    if not os.path.isdir(model_dir):
        raise FileNotFoundError(f"Model directory not found: {model_dir}")

    for sub, files in _module_files(model_dir).items():
        module = Module(id="wmoop." + sub, dir_name=sub)
        for f in files:
            with open(f, encoding="utf-8") as fh:
                docs = [d for d in yaml.safe_load_all(fh) if d]
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                if "module" in doc and isinstance(doc["module"], dict):
                    m = doc["module"]
                    module.id = m.get("id", module.id)
                    module.version = str(m.get("version", "0.0.0"))
                    module.title = m.get("title", "")
                    module.depends_on = [
                        dep.get("module") for dep in (m.get("depends_on") or []) if isinstance(dep, dict)
                    ]
                for c in doc.get("concepts") or []:
                    module.concepts.append(_concept(c, module.id))
                for r in doc.get("roles") or []:
                    module.roles.append(_role(r, module.id))
                for e in doc.get("enumerations") or []:
                    module.enumerations.append(_enum(e))
                for d in doc.get("datatypes") or []:
                    module.datatypes.append(_datatype(d))
                for i in doc.get("individuals") or []:
                    module.individuals.append(_individual(i))
        wm.modules[module.id] = module

    for m in wm.modules.values():
        for c in m.concepts:
            c.module = m.id
            wm.concepts[c.id] = c
        for r in m.roles:
            r.module = m.id
            wm.roles[r.id] = r
        for e in m.enumerations:
            e.module = m.id
            wm.enumerations[e.id] = e
        for d in m.datatypes:
            d.module = m.id
            wm.datatypes[d.id] = d
        for i in m.individuals:
            i.module = m.id
            wm.individuals[i.id] = i
    for r in wm.roles.values():
        if r.played_by:
            wm.role_bearing.add(r.played_by)
    return wm
