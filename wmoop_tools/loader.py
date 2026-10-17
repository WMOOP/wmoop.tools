"""Parse WML (*.wml.yaml) files into a :class:`WorldModel`.

Each top-level folder under the model directory is one module; a module may be split
across several ``*.wml.yaml`` files (e.g. ``transport.wml.yaml`` + ``roles.wml.yaml``).
"""
from __future__ import annotations

import glob
import os

import yaml

from .model import Concept, Enumeration, EnumValue, Module, Property, Role, WorldModel


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


def _concept(d: dict, module_id: str) -> Concept:
    return Concept(
        id=d["id"],
        name=d.get("name", d["id"].split("/")[-1]),
        kind=d.get("kind", "concrete"),
        extends=d.get("extends"),
        implements=list(d.get("implements") or []),
        properties=[_prop(p) for p in (d.get("properties") or [])],
        definition=d.get("definition"),
        module=module_id,
    )


def _role(d: dict, module_id: str) -> Role:
    return Role(
        id=d["id"],
        name=d.get("name", d["id"].split("/")[-1]),
        played_by=d.get("played_by"),
        context=d.get("context"),
        properties=[_prop(p) for p in (d.get("properties") or [])],
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


def load_model(model_dir: str) -> WorldModel:
    wm = WorldModel()
    model_dir = os.path.abspath(model_dir)
    if not os.path.isdir(model_dir):
        raise FileNotFoundError(f"Model directory not found: {model_dir}")

    subdirs = sorted(e for e in os.listdir(model_dir) if os.path.isdir(os.path.join(model_dir, e)))
    for sub in subdirs:
        files = sorted(glob.glob(os.path.join(model_dir, sub, "*.wml.yaml")))
        if not files:
            continue
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
                    module.depends_on = [dep.get("module") for dep in (m.get("depends_on") or []) if isinstance(dep, dict)]
                for c in (doc.get("concepts") or []):
                    module.concepts.append(_concept(c, module.id))
                for r in (doc.get("roles") or []):
                    module.roles.append(_role(r, module.id))
                for e in (doc.get("enumerations") or []):
                    module.enumerations.append(_enum(e))
        wm.modules[module.id] = module

    for m in wm.modules.values():
        for c in m.concepts:
            c.module = m.id
            wm.concepts[c.id] = c
        for r in m.roles:
            r.module = m.id
            wm.roles[r.id] = r
        for e in m.enumerations:
            wm.enumerations[e.id] = e
    for r in wm.roles.values():
        if r.played_by:
            wm.role_bearing.add(r.played_by)
    return wm
