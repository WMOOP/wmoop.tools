"""What the generators share: module paths, cardinalities, type resolution, units, invariants,
individuals and the banner.

Language-specific spelling (identifiers, type names, files) stays in each generator.
"""

from __future__ import annotations

import contextlib
import datetime
import math
import os
import re
from dataclasses import dataclass

from .. import __version__
from ..compile import QUANTITY_KIND, UNIT, ModelError, all_properties, concept_chain
from ..model import Concept, Invariant, Property, Relation

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


def _card(text: str, where: str) -> Card:
    lo, sep, hi = text.strip().partition("..")
    if not sep:
        hi = lo
    try:
        lower = int(lo)
        upper = None if hi == "*" else int(hi)
    except ValueError as exc:
        raise ModelError(f"{where}: unreadable cardinality {text!r}") from exc
    return Card(lower, upper)


def cardinality(p) -> Card:
    """``"0..1"``, ``"1"``, ``"1..*"`` -> lower/upper bounds; a legacy ``required: true`` raises the lower bound."""
    card = _card(str(p.cardinality or "0..1"), p.id)
    if getattr(p, "required", False) and card.lower == 0:
        return Card(1, card.upper)
    return card


def max_per_player(role) -> int | None:
    """How many roles of this type one player may hold at once (``cardinality_per_player``); None: any number."""
    return _card(str(role.cardinality_per_player or "0..*"), f"{role.id} cardinality_per_player").upper


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
    for ind in module.individuals:
        for v in individual_values(wm, ind):  # an inherited property's type may come from yet another module
            if v.type.module:
                refs.add(v.type.module)
            if v.type.kind == "concept":
                refs.update(wm.individuals[i].module for i in v.items)
    refs.discard(module.id)
    return sorted(refs)


# --- Units --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitEntry:
    """A ``wmoop.core/Unit`` individual: a value in it is ``factor * value + offset`` in its kind's canonical unit."""

    symbol: str
    id: str
    kind: str  # the QuantityKind it measures, e.g. wmoop.core/Speed
    factor: float
    offset: float


def unit_catalog(wm) -> list[UnitEntry]:
    """The model's unit catalogue (docs/02-meta-model.md §6.4): every ``wmoop.core/Unit`` individual, in model order.

    Empty when the model has none, e.g. without a ``wmoop.core`` module.
    """
    unit = wm.concepts.get(UNIT)
    defaults = {p.name: p.default for p in unit.properties if p.default is not None} if unit else {}
    entries: list[UnitEntry] = []
    seen: dict[str, str] = {}
    for ind in wm.individuals.values():
        if ind.instance_of != UNIT:
            continue
        values = defaults | ind.values
        symbol, kind = values.get("symbol"), values.get("quantityKind")
        factor, offset = values.get("factor", 1), values.get("offset", 0)
        if not (isinstance(symbol, str) and symbol and isinstance(kind, str) and _number(factor) and _number(offset)):
            raise ModelError(f"{ind.id}: a unit needs a symbol, a quantityKind, and a numeric factor and offset")
        if factor == 0:
            raise ModelError(f"{ind.id}: a unit's factor cannot be 0")
        if symbol in seen:
            raise ModelError(f"{ind.id}: unit symbol {symbol!r} is already the symbol of {seen[symbol]}")
        seen[symbol] = ind.id
        entries.append(UnitEntry(symbol, ind.id, kind, factor, offset))
    return entries


def quantity_kind(wm, p) -> str:
    """The QuantityKind a quantity property measures: its ``type`` when that is a QuantityKind
    individual, else its unit's kind in the catalogue; empty when the model does not say."""
    kind = wm.individuals.get(p.type or "")
    if kind is not None and kind.instance_of == QUANTITY_KIND:
        return kind.id
    return next((u.kind for u in unit_catalog(wm) if u.symbol == p.unit), "")


# The QuantityKind properties that hold its SI dimension vector (L, M, T, I, Θ, N, J).
DIMENSIONS = ("dimL", "dimM", "dimT", "dimI", "dimTheta", "dimN", "dimJ")


def kind_dimensions(wm) -> dict[str, tuple[int, ...]]:
    """The SI dimension of every ``wmoop.core/QuantityKind`` individual that records one, by kind.

    Two kinds with the same dimension (Count and Angle) are still different kinds: the kernels tell
    WM-QUANTITYKIND-MISMATCH from WM-UNIT-DIMENSION-MISMATCH with it.
    """
    concept = wm.concepts.get(QUANTITY_KIND)
    defaults = {p.name: p.default for p in concept.properties if p.default is not None} if concept else {}
    out: dict[str, tuple[int, ...]] = {}
    for ind in wm.individuals.values():
        values = defaults | ind.values
        if ind.instance_of != QUANTITY_KIND or not any(d in values for d in DIMENSIONS):
            continue
        dimension = tuple(values.get(d, 0) for d in DIMENSIONS)
        if not all(isinstance(e, int) and not isinstance(e, bool) for e in dimension):
            raise ModelError(f"{ind.id}: a dimension exponent must be an integer")
        out[ind.id] = dimension
    return out


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# --- Invariants ---------------------------------------------------------------------------------

# A simple invariant clause, as wmoop.doc's validator reads it: ``self.<property> <op> <literal>``.
# Clauses may be joined by ``and``; anything richer waits for WMX (ADR 0002).
SIMPLE_INVARIANT = re.compile(
    r"^self\.([a-z][A-Za-z0-9]*)\s*(<=|>=|==|!=|<|>)\s*"
    r"(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|'[^']*'|\"[^\"]*\")$"
)
_NUMERIC = frozenset({"integer", "decimal", "quantity"})


@dataclass(frozen=True)
class Clause:
    """``self.<prop> <op> <literal>``: a comparison every instance must satisfy while ``prop`` has a value."""

    prop: Property
    type: TypeRef
    op: str
    literal: object  # int | float | bool | str (an enumeration value id, for an enum property)
    text: str  # the literal as the model writes it


@dataclass(frozen=True)
class Check:
    """A simple invariant of ``owner``: each of its clauses must hold."""

    owner: Concept
    invariant: Invariant
    clauses: tuple[Clause, ...]

    @property
    def message(self) -> str:
        """What a violation raises: the model's message, then the invariant's id and expression."""
        text = self.invariant.message or f"{local(self.owner.id)} must satisfy {self.invariant.expr}."
        return f"{' '.join(text.split())} [{self.invariant.id}: {self.invariant.expr}]"


def invariants(wm, concept) -> tuple[list[Check], list[Invariant]]:
    """``concept``'s own invariants, split into the simple ones the generated constructors check and
    those that wait for WMX (ADR 0002)."""
    props = {p.name: p for p in all_properties(wm, concept)}
    checks: list[Check] = []
    pending: list[Invariant] = []
    for inv in concept.invariants:
        parts = [SIMPLE_INVARIANT.match(part) for part in re.split(r"\s+and\s+", inv.expr.strip())]
        if not all(parts):
            pending.append(inv)
            continue
        where = f"{concept.id} invariant {inv.id}"
        clauses = tuple(_clause(wm, where, props, *m.groups()) for m in parts if m)
        checks.append(Check(concept, inv, clauses))
    return checks, pending


def _clause(wm, where: str, props: dict, name: str, op: str, text: str) -> Clause:
    p = props.get(name)
    if p is None:
        raise ModelError(f"{where}: there is no property '{name}' to compare")
    if cardinality(p).many:
        raise ModelError(f"{where}: '{name}' holds several values, which a simple invariant cannot compare")
    t = resolve_type(wm, p)
    if text in ("true", "false"):
        literal: object = text == "true"
    elif text[0] in "'\"":
        literal = text[1:-1]
    else:
        literal = float(text) if any(ch in text for ch in ".eE") else int(text)
    numeric = isinstance(literal, (int, float)) and not isinstance(literal, bool)
    if t.kind in _NUMERIC and numeric:
        return Clause(p, t, op, literal, text)
    if op in ("==", "!=") and (
        (t.kind == "boolean" and isinstance(literal, bool)) or (t.kind == "string" and isinstance(literal, str))
    ):
        return Clause(p, t, op, literal, text)
    if op in ("==", "!=") and t.kind == "enum" and isinstance(literal, str):
        if literal not in {v.id for v in wm.enumerations[t.target].values}:
            raise ModelError(f"{where}: {text} is not a value of {t.target}")
        return Clause(p, t, op, literal, text)
    raise ModelError(f"{where}: {name} ({t.kind}) cannot be compared with {text} using {op}")


def declared_on(wm, concept, prop: Property) -> Concept:
    """The class in ``concept``'s chain that declares ``prop``."""
    return next(c for c in concept_chain(wm, concept) if any(p is prop for p in c.properties))


def narrowed(wm) -> set[tuple[str, str]]:
    """``(concept id, property name)`` for every property a subclass's invariant narrows.

    The C# generator makes these properties ``virtual``, so the subclass can override them with its check.
    """
    out: set[tuple[str, str]] = set()
    for c in wm.concepts.values():
        for check in invariants(wm, c)[0]:
            for clause in check.clauses:
                owner = declared_on(wm, c, clause.prop)
                if owner is not c:
                    out.add((owner.id, clause.prop.name))
    return out


# --- Individuals --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Value:
    """An individual's value for one property, checked against the property's type."""

    prop: Property
    type: TypeRef
    many: bool
    items: tuple  # numbers, strings, booleans, dates, enumeration value ids or individual ids, by type


def individual_class(wm, ind) -> Concept:
    """The concrete concept ``ind`` instantiates. A generator puts the individual on that class, so the
    concept must be declared in the individual's own module."""
    c = wm.concepts.get(ind.instance_of)
    if c is None or c.kind == "abstract":
        raise ModelError(f"{ind.id}: instance_of '{ind.instance_of}' is not a concrete concept")
    if c.module != ind.module:
        raise ModelError(
            f"{ind.id}: an individual is generated on its concept's class, so it must be declared "
            f"in {c.module}, the module of {c.id}"
        )
    return c


def individual_values(wm, ind) -> list[Value]:
    """``ind``'s values, in the order its class declares the properties (root first)."""
    c = individual_class(wm, ind)
    props = all_properties(wm, c)
    unknown = sorted(set(ind.values) - {p.name for p in props})
    if unknown:
        raise ModelError(f"{ind.id}: {', '.join(unknown)} is not a property of {c.id}")
    out: list[Value] = []
    for p in props:
        t, card = resolve_type(wm, p), cardinality(p)
        if p.name not in ind.values:
            if card.required and p.default is None:
                raise ModelError(f"{ind.id}: no value for the required property {p.id}")
            continue
        raw = ind.values[p.name]
        if isinstance(raw, list) and not card.many:
            raise ModelError(f"{ind.id}: a list for the single-valued property {p.id}")
        items = raw if isinstance(raw, list) else [raw]
        if len(items) < card.lower or (card.upper is not None and len(items) > card.upper):
            raise ModelError(f"{ind.id}: {len(items)} value(s) for {p.id}, outside its cardinality {p.cardinality}")
        out.append(Value(p, t, card.many, tuple(_item(wm, ind, p, t, v) for v in items)))
    return out


def _item(wm, ind, p, t: TypeRef, v):
    """``v`` as a value of type ``t``: a date parsed, an enumeration value as its id; anything else is a model error."""
    if t.kind in ("quantity", "decimal"):
        ok = _number(v)
    elif t.kind == "integer":
        ok = isinstance(v, int) and not isinstance(v, bool)
    elif t.kind == "string":
        ok = isinstance(v, str)
    elif t.kind == "boolean":
        ok = isinstance(v, bool)
    elif t.kind == "date":
        if isinstance(v, str):
            with contextlib.suppress(ValueError):
                v = datetime.date.fromisoformat(v)
        ok = isinstance(v, datetime.date) and not isinstance(v, datetime.datetime)
    elif t.kind == "enum":
        v = str(v)
        ok = v in {e.id for e in wm.enumerations[t.target].values}
    elif t.kind == "concept":
        ref = wm.individuals.get(v) if isinstance(v, str) else None
        ok = ref is not None and any(c.id == t.target for c in concept_chain(wm, individual_class(wm, ref)))
    else:  # a role cannot be a reference value
        ok = False
    if not ok:
        raise ModelError(f"{ind.id}: {v!r} is not a value of {p.id} ({t.target or t.kind})")
    return v


def module_individuals(wm, module) -> list:
    """``module``'s individuals in model order, each moved after the ones of this module its values refer to."""
    order: list = []
    placed: set[str] = set()
    pending = list(module.individuals)
    while pending:
        ready = [
            ind
            for ind in pending
            if all(
                r in placed or wm.individuals[r].module != module.id
                for v in individual_values(wm, ind)
                if v.type.kind == "concept"
                for r in v.items
            )
        ]
        if not ready:
            raise ModelError(
                f"{module.id}: these individuals refer to each other in a cycle: " + ", ".join(i.id for i in pending)
            )
        order += ready
        placed.update(i.id for i in ready)
        pending = [i for i in pending if i.id not in placed]
    return order


# --- Relations ----------------------------------------------------------------------------------


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


# --- Files --------------------------------------------------------------------------------------


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
