"""Generate an idiomatic Python binding from a compiled WorldModel.

Generated code is DATA only (classes, properties, inheritance, enums, roles). Behaviour
(algorithms such as ``can_drive`` or ``describe``) is deliberately NOT generated — it is
hand-written as extensions/visitors/strategies (the "generation gap"; see PATTERNS.md).
"""
from __future__ import annotations

import os

from ..compile import all_properties, inherited_properties, topo_concepts

RUNTIME = '''"""Generated runtime kernel for the WMOOP Python binding. DO NOT EDIT."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ConceptId:
    value: str

    def __post_init__(self):
        if not self.value or not self.value.strip():
            raise ValueError("A ConceptId must be a non-empty identifier.")

    def __str__(self):
        return self.value


def _coerce_id(x):
    return x if isinstance(x, ConceptId) else ConceptId(x)


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str

    def __post_init__(self):
        if not self.unit or not self.unit.strip():
            raise ValueError("A Quantity must carry a unit.")

    def __str__(self):
        return f"{self.value:g} {self.unit}"


class Entity(ABC):
    def __init__(self, id, name):
        self._id = _coerce_id(id)
        self._name = name

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    def __str__(self):
        return f"{self._name} [{self._id}]"


class Role(ABC):
    def __init__(self):
        self._subject = None

    @property
    @abstractmethod
    def role_type(self):
        ...

    @property
    def subject(self):
        return self._subject

    def _attach(self, subject):
        if self._subject is not None:
            raise RuntimeError("Role is already attached to a subject.")
        self._subject = subject


class HasRoles:
    def _init_roles(self):
        self._roles = []

    @property
    def roles(self):
        return tuple(self._roles)

    def add_role(self, role):
        role._attach(self)
        self._roles.append(role)
        return role

    def has_role(self, role_cls):
        return self.get_role(role_cls) is not None

    def get_role(self, role_cls):
        for r in self._roles:
            if isinstance(r, role_cls):
                return r
        return None
'''


def _local(cid: str) -> str:
    return cid.split("/")[-1]


def _doc(text) -> str:
    return (text or "").strip().replace("\n", " ").replace('"', "'")


def _default_literal(p) -> str:
    d = p.default
    if d is None:
        return "None"
    if isinstance(d, bool):
        return "True" if d else "False"
    if isinstance(d, (int, float)):
        return repr(d)
    return repr(d)


def _w(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _emit_concept(wm, c) -> str:
    name = _local(c.id)
    base = _local(c.extends) if c.extends else "Entity"
    role_bearing = c.id in wm.role_bearing
    bases = base + (", HasRoles" if role_bearing else "")

    allp = all_properties(wm, c)
    inh = inherited_properties(wm, c)
    own = c.properties

    lines = [f"class {name}({bases}):"]
    lines.append(f'    """{name} — {c.id}. {_doc(c.definition)}"""')
    lines.append(f'    WM_ID = "{c.id}"')
    lines.append(f'    WM_KIND = "{c.kind}"')

    sig = ""
    if allp:
        sig = ", *" + "".join(f", {p.name}={_default_literal(p)}" for p in allp)
    lines.append(f"    def __init__(self, id, name{sig}):")
    if c.kind == "abstract":
        lines.append(f"        if type(self) is {name}:")
        lines.append(f'            raise TypeError("{name} is abstract and cannot be instantiated directly.")')
    if base == "Entity":
        lines.append("        super().__init__(id, name)")
    else:
        inh_args = "".join(f", {p.name}={p.name}" for p in inh)
        lines.append(f"        super().__init__(id, name{inh_args})")
    if role_bearing:
        lines.append("        self._init_roles()")
    for p in own:
        lines.append(f"        self._{p.name} = {p.name}")

    for p in own:
        lines.append("    @property")
        lines.append(f"    def {p.name}(self):")
        lines.append(f"        return self._{p.name}")
    lines.append("")
    return "\n".join(lines)


def _emit_role(wm, r) -> str:
    name = _local(r.id)
    lines = [f"class {name}(Role):"]
    lines.append(f'    """{name} role — {r.id}. {_doc(r.definition)}"""')
    lines.append(f'    WM_ID = "{r.id}"')
    if r.played_by:
        lines.append(f'    WM_PLAYED_BY = "{r.played_by}"')

    sig = ""
    if r.properties:
        sig = ", *" + "".join(f", {p.name}={_default_literal(p)}" for p in r.properties)
    lines.append(f"    def __init__(self{sig}):")
    lines.append("        super().__init__()")
    for p in r.properties:
        lines.append(f"        self._{p.name} = {p.name}")

    lines.append("    @property")
    lines.append("    def role_type(self):")
    lines.append("        return ConceptId(self.WM_ID)")
    for p in r.properties:
        lines.append("    @property")
        lines.append(f"    def {p.name}(self):")
        lines.append(f"        return self._{p.name}")
    lines.append("")
    return "\n".join(lines)


def generate_python(wm, out_dir: str) -> list:
    pkg = os.path.join(out_dir, "wmoop_model")
    written = []

    rt = os.path.join(pkg, "_runtime.py")
    _w(rt, RUNTIME)
    written.append(rt)

    module_files = []
    for m in wm.modules.values():
        fname = m.dir_name or m.id.split(".")[-1]
        module_files.append(fname)
        body = [f'"""Generated from module {m.id} v{m.version}. DO NOT EDIT — regenerate with wmoop.tools."""']
        body.append("from __future__ import annotations")
        if m.enumerations:
            body.append("from enum import Enum")
        body.append("from ._runtime import ConceptId, Entity, Quantity, Role, HasRoles  # noqa: F401")

        local_ids = {c.id for c in m.concepts}
        cross = set()
        for c in m.concepts:
            if c.extends and c.extends not in local_ids and c.extends in wm.concepts:
                other = wm.concepts[c.extends].module
                cross.add((wm.modules[other].dir_name, _local(c.extends)))
        for omf, nm in sorted(cross):
            body.append(f"from .{omf} import {nm}")
        body.append("")

        for e in m.enumerations:
            body.append(f"class {_local(e.id)}(str, Enum):")
            body.append(f'    """{_local(e.id)} — {e.id}."""')
            if not e.values:
                body.append("    pass")
            for v in e.values:
                body.append(f'    {v.id} = "{v.id}"')
            body.append("")

        for c in topo_concepts(m, wm):
            body.append(_emit_concept(wm, c))
        for r in m.roles:
            body.append(_emit_role(wm, r))

        path = os.path.join(pkg, fname + ".py")
        _w(path, "\n".join(body))
        written.append(path)

    init = ['"""Generated WMOOP model package. DO NOT EDIT — regenerate with wmoop.tools."""']
    for nm in module_files:
        init.append(f"from . import {nm} as {nm}  # noqa: F401")
    ipath = os.path.join(pkg, "__init__.py")
    _w(ipath, "\n".join(init))
    written.append(ipath)
    return written
