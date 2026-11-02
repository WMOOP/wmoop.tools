"""What the generators share: module paths, cardinalities, type resolution and the banner.

Language-specific spelling (identifiers, type names, files) stays in each generator.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .. import __version__
from ..compile import ModelError
from ..model import Relation

PRIMITIVES = frozenset({"string", "integer", "decimal", "boolean", "date"})
TEMPLATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
CORE_MODULE = "wmoop.core"


def local(qname: str) -> str:
    """``wmoop.transport/Moped`` -> ``Moped``."""
    return qname.split("/")[-1]


def module_path(module_id: str) -> list[str]:
    """``wmoop.transport`` -> ``["transport"]``: the segments under the ``wmoop`` root (§4.2)."""
    parts = module_id.split(".")
    if parts[0] != "wmoop" or len(parts) < 2 or not all(parts):
        raise ModelError(f"module id {module_id!r} is not of the form wmoop.<domain>")
    return parts[1:]


def snake(name: str) -> str:
    """``licenceNumber`` -> ``licence_number``; ``ISCEDLevel`` -> ``isced_level``."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    return s.lower()


def pascal(name: str) -> str:
    return name[:1].upper() + name[1:]


@dataclass(frozen=True)
class Card:
    lower: int
    upper: int | None  # None = unbounded

    @property
    def many(self) -> bool:
        return self.upper is None or self.upper > 1

    @property
    def required(self) -> bool:
        return self.lower >= 1


def cardinality(p) -> Card:
    """``"0..1"``, ``"1"``, ``"1..*"`` -> lower/upper bounds; a legacy ``required: true`` raises the lower bound."""
    text = str(p.cardinality or "0..1").strip()
    lo, sep, hi = text.partition("..")
    if not sep:
        hi = lo
    try:
        lower = int(lo)
        upper = None if hi == "*" else int(hi)
    except ValueError as exc:
        raise ModelError(f"{p.id}: unreadable cardinality {text!r}") from exc
    if getattr(p, "required", False) and lower == 0:
        lower = 1
    return Card(lower, upper)


@dataclass(frozen=True)
class TypeRef:
    """What a property holds, independent of the target language."""

    kind: str  # "quantity" | a primitive (see PRIMITIVES) | "enum" | "concept" | "role"
    target: str = ""  # the qname, for enum / concept / role
    module: str = ""  # the module that declares the target


def resolve_type(wm, p) -> TypeRef:
    """Map a property to a :class:`TypeRef`; an unmappable type is a model error, never ``object``."""
    if p.unit:
        return TypeRef("quantity")
    t = p.type or ""
    if t in PRIMITIVES:
        return TypeRef(t)
    if t in wm.datatypes:
        base = wm.datatypes[t].base
        if base in PRIMITIVES:
            return TypeRef(base)
        raise ModelError(f"{p.id}: datatype {t} has no primitive base")
    if t in wm.enumerations:
        return TypeRef("enum", t, wm.enumerations[t].module)
    if t in wm.concepts:
        return TypeRef("concept", t, wm.concepts[t].module)
    if t in wm.roles:
        return TypeRef("role", t, wm.roles[t].module)
    raise ModelError(
        f"{p.id}: cannot map type {t!r} - not a primitive, datatype, enumeration, concept or role "
        "(a quantity needs a unit)"
    )


def module_of(wm, qname: str) -> str:
    for table in (wm.concepts, wm.roles, wm.enumerations, wm.datatypes):
        if qname in table:
            return table[qname].module
    raise ModelError(f"unknown type {qname}")


def referenced_modules(wm, module) -> list[str]:
    """Every other module whose types this module's classes extend, hold or relate to, sorted."""
    refs: set[str] = set()
    for c in module.concepts:
        if c.extends:
            refs.add(module_of(wm, c.extends))
    for owner in [*module.concepts, *module.roles]:
        for p in owner.properties:
            t = resolve_type(wm, p)
            if t.module:
                refs.add(t.module)
        for r in owner.relations:
            refs.add(module_of(wm, r.target))
    refs.discard(module.id)
    return sorted(refs)


@dataclass(frozen=True)
class RelationEnd:
    """One navigable end of a relation, as generated on the class ``holder``.

    A relation declared on its owner gives the forward end there. Its ``inverse`` gives a to-many end
    on the target, but only inside one module, so a base package never depends on the packages that
    extend it (docs/03-architecture.md §4.5).
    """

    holder: str  # the class that holds this end
    name: str  # the member name in the model, e.g. "partOf" / "contains"
    other: str  # the element type: the class at the other end
    many: bool
    opposite: str | None  # the member name of the other end, when the relation is navigable both ways
    relation: Relation
    inverse: bool  # True for the end generated from `inverse:`


def _two_way(wm, owner, r) -> str | None:
    if not r.inverse or module_of(wm, r.target) != owner.module:
        return None
    return r.inverse.partition("#")[2]


def relation_ends(wm, holder) -> list[RelationEnd]:
    """The relation ends generated on ``holder`` (a concept or role): its own, then the inverse ones."""
    ends = []
    for r in holder.relations:
        many = cardinality(r).many
        ends.append(RelationEnd(holder.id, r.name, r.target, many, _two_way(wm, holder, r), r, False))
    for owner in [*wm.concepts.values(), *wm.roles.values()]:
        if owner.module != holder.module:
            continue
        for r in owner.relations:
            inverse = _two_way(wm, owner, r)
            if inverse and r.target == holder.id:
                ends.append(RelationEnd(holder.id, inverse, owner.id, True, r.name, r, True))
    return ends


def banner(comment: str, module=None, hint: str = "") -> str:
    """The machine-readable header every generated file opens with (docs/03-architecture.md §2.3)."""
    lines = ["<auto-generated>", f"  tool: wmoop.tools {__version__}"]
    if module is not None:
        lines.append(f"  model: {module.id} {module.version}")
    lines.append("  DO NOT EDIT. Changes are overwritten by the next regeneration.")
    if hint:
        lines.append(f"  {hint}")
    lines.append("</auto-generated>")
    return "\n".join(f"{comment} {line}" for line in lines)


def template(*parts: str) -> str:
    with open(os.path.join(TEMPLATES, *parts), encoding="utf-8") as f:
        return f.read()


def write(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path
