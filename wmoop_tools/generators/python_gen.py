"""Generate the Python binding: one module per WML module, in the ``wmoop`` namespace package.

Layout under ``out_dir`` (a binding's ``generated/``)::

    wmoop/_kernel.py      errors, identity, quantities, roles and the extension hook (from templates/python),
                          plus the model's unit catalogue
    wmoop/core.py         the wmoop.core module, plus the kernel's public names
    wmoop/<domain>.py     one per WML module, e.g. wmoop/transport.py

``wmoop`` has no ``__init__.py`` (a PEP 420 namespace package), so per-domain distributions and a
binding's hand-written packages can share it.

Names follow docs/03-architecture.md §4.2: ``wmoop.transport.Moped``, ``wheel_count``. A constructor
takes ``id`` and ``name``, then every property as a keyword argument, so reordering properties in the
model never breaks a caller. Required slots have no default; an optional slot defaults to ``None``,
never to a value that would read as a fact.

The constructor checks what the model states: a quantity's unit is of the property's kind, and the
simple invariants (``self.<property> <op> <literal>``) hold. The model's individuals are instances on
the class they instantiate, e.g. ``wmoop.space.Planet.Earth`` or ``wmoop.core.Unit.Kilometre``.

Behaviour is not generated. Each class lists ``<Name>Ext`` from ``wmoop_ext.<domain>`` first among its
bases when the binding defines one (the Python generation gap, PATTERNS.md §3.3)::

    # wmoop_ext/transport.py  (hand-written, in the binding)
    class MopedExt:
        def describe(self) -> str: ...

A mixin is a plain class: it does not subclass a generated class or define ``__init__``, and it
imports generated types inside its methods, because the generated module imports it while loading.
"""

from __future__ import annotations

import keyword
import os

from ..compile import ModelError, all_properties, inherited_properties, topo_concepts
from .common import (
    CORE_MODULE,
    Clause,
    TypeRef,
    banner,
    cardinality,
    individual_class,
    individual_values,
    invariants,
    kind_dimensions,
    local,
    max_per_player,
    module_individuals,
    module_of,
    module_path,
    quantity_kind,
    referenced_modules,
    relation_ends,
    resolve_type,
    snake,
    template,
    unit_catalog,
    write,
)

# Members of Entity / Role that a property must not shadow.
_KERNEL_MEMBERS = frozenset({"id", "name", "roles", "is_a", "add_role", "has_role", "get_role", "role_type", "subject"})
_PRIMITIVE = {"string": "str", "integer": "int", "decimal": "float", "boolean": "bool", "date": "datetime.date"}
_KERNEL_IMPORT = (
    "from wmoop._kernel import (  # noqa: F401\n"
    "    ConceptId, Entity, Many, One, Quantity, Role, WmoopError, WmoopStateError, WmoopTypeError, WmoopValueError,\n"
    "    check_quantity, ext,\n"
    ")"
)
_EXT_HINT = "Add behaviour as a mixin <Name>Ext in wmoop_ext.{module} (see wmoop_tools/generators/python_gen.py)."


def ident(name: str) -> str:
    """A valid, collision-free Python name: keywords and kernel members get a trailing underscore."""
    return name + "_" if keyword.iskeyword(name) or name in _KERNEL_MEMBERS else name


def prop_name(p) -> str:
    return ident(snake(p.name))


def dotted(module_id: str) -> str:
    """``wmoop.transport`` -> ``transport`` (the module's path under ``wmoop``)."""
    return ".".join(module_path(module_id))


def _alias(module_id: str) -> str:
    return "_" + "_".join(module_path(module_id))


def _doc(*parts: str | None) -> str:
    """A docstring literal; falls back to repr() when the text could break a triple-quoted string."""
    text = " ".join(" ".join((p or "").split()) for p in parts if p)
    if '"' in text or "\\" in text:
        return repr(text)
    return f'"""{text}"""'


def _type_name(qname: str, module_id: str, here: str) -> str:
    return local(qname) if module_id == here else f"{_alias(module_id)}.{local(qname)}"


def _annotation(t: TypeRef, here: str) -> str:
    if t.kind == "quantity":
        return "Quantity"
    if t.kind in _PRIMITIVE:
        return _PRIMITIVE[t.kind]
    return _type_name(t.target, t.module, here)


def _default_literal(wm, p) -> str:
    d = p.default
    if isinstance(d, (int, float)) and not isinstance(d, bool) and resolve_type(wm, p).kind == "quantity":
        return f"Quantity({d!r}, {p.unit!r})"
    if isinstance(d, (bool, int, float, str)):
        return repr(d)
    raise ModelError(f"{p.id}: unsupported default {d!r} (use a boolean, number or string)")


def _param(wm, p, here: str) -> str:
    t, card = resolve_type(wm, p), cardinality(p)
    ann = _annotation(t, here)
    name = prop_name(p)
    if card.many:
        return f"{name}: Iterable[{ann}]" + ("" if card.required else " = ()")
    if p.default is not None:
        return f"{name}: {ann} = {_default_literal(wm, p)}"
    if card.required:
        return f"{name}: {ann}"
    return f"{name}: {ann} | None = None"


def _store(wm, p, here: str) -> list[str]:
    t, card = resolve_type(wm, p), cardinality(p)
    # The escaped name keeps a model property `name` (stored as `_wm_name_`) off the kernel's `_wm_name`.
    name = prop_name(p)
    attr = f"self._wm_{name}"
    enum = _annotation(t, here) if t.kind == "enum" else None
    converts = enum is not None or t.kind == "quantity"

    def convert(v: str) -> str:
        if t.kind == "quantity":  # the unit must be of the property's kind
            return f"check_quantity({v}, {p.unit!r}, {quantity_kind(wm, p)!r}, {name!r})"
        return f"{enum}({v})" if enum else v

    if card.many:
        items = f"tuple({convert('v')} for v in {name})" if converts else f"tuple({name})"
        lines = [f"        {attr} = {items}"]
        if card.required:
            lines += [
                f"        if not {attr}:",
                f'            raise WmoopValueError("WM-CARDINALITY", "{name} needs at least one value.")',
            ]
        return lines
    lines = []
    if card.required and p.default is None:
        lines += [
            f"        if {name} is None:",
            f'            raise WmoopValueError("WM-REQUIRED-MISSING", "{name} is required.")',
        ]
    if not converts or card.required or p.default is not None:
        value = convert(name)
    else:
        value = f"None if {name} is None else {convert(name)}"
    return [*lines, f"        {attr} = {value}"]


def _comparison(c: Clause, subject: str, here: str) -> str:
    """A clause of a simple invariant as a Python condition on ``subject``."""
    if c.type.kind == "quantity":
        return f"{subject}.in_({c.prop.unit!r}) {c.op} {c.text}"
    if c.type.kind in ("integer", "decimal"):
        return f"{subject} {c.op} {c.text}"
    if c.type.kind == "boolean":
        return f"{subject} {'is' if c.op == '==' else 'is not'} {c.literal!r}"
    if c.type.kind == "enum":
        return f"{subject} {c.op} {_type_name(c.type.target, c.type.module, here)}.{ident(str(c.literal))}"
    return f"{subject} {c.op} {c.literal!r}"


def _checks(wm, c, here: str) -> list[str]:
    """The constructor lines that raise when one of ``c``'s simple invariants does not hold.

    A clause on an absent value holds, as in wmoop.doc's validator: the open world does not know it.
    """
    lines = []
    for check in invariants(wm, c)[0]:
        for clause in check.clauses:
            subject = f"self.{prop_name(clause.prop)}"
            always = cardinality(clause.prop).required and clause.prop.default is None
            guard = "" if always else f"{subject} is not None and "
            test = _comparison(clause, subject, here)
            lines += [
                f"        if {guard}not ({test}):",
                f'            raise WmoopValueError("WM-INVARIANT-FAILED", {check.message!r})',
            ]
    return lines


def _getter(wm, p, here: str) -> list[str]:
    t, card = resolve_type(wm, p), cardinality(p)
    ann = _annotation(t, here)
    if card.many:
        ann = f"tuple[{ann}, ...]"
    elif not card.required and p.default is None:
        ann += " | None"
    return [
        "",
        "    @property",
        f"    def {prop_name(p)}(self) -> {ann}:",
        f"        {_doc(p.definition or p.name)}",
        f"        return self._wm_{prop_name(p)}",
    ]


def _init(wm, here: str, every: list, inherited: list, own: list, *, role: bool, checks: list[str]) -> list[str]:
    params = ", ".join(_param(wm, p, here) for p in every)
    head = "self, *" if role else "self, id: ConceptId | str, name: str, *"
    lines = ["", f"    def __init__({head}, {params}) -> None:"]
    if role:
        lines.append("        super().__init__()")
    else:
        passed = "".join(f", {prop_name(p)}={prop_name(p)}" for p in inherited)
        lines.append(f"        super().__init__(id, name{passed})")
    for p in own:
        lines += _store(wm, p, here)
    return lines + checks


def _emit_enum(e) -> list[str]:
    name = local(e.id)
    lines = [f"class {name}(str, Enum):", f"    {_doc(name, '-', e.id + '.', e.definition)}"]
    for v in e.values:
        lines.append(f"    {ident(v.id)} = {v.id!r}")
    return [*lines, "", ""]


def _relations(wm, holder, here: str) -> list[str]:
    """Class-level relation ends: ``One`` (to-one) / ``Many`` (to-many) descriptors from the kernel."""
    taken = {prop_name(p) for p in holder.properties}
    lines = []
    for end in relation_ends(wm, holder):
        attr = ident(snake(end.name))
        if attr in taken:
            raise ModelError(f"{holder.id}: relation end '{end.name}' clashes with another member")
        taken.add(attr)
        other = module_of(wm, end.other)
        target = local(end.other) if other == here else f"wmoop.{dotted(other)}.{local(end.other)}"
        args = [repr(target)]
        if end.opposite:
            args.append(f"inverse={ident(snake(end.opposite))!r}")
        doc = f"Inverse of {end.relation.id}." if end.inverse else (end.relation.definition or end.name)
        args.append(f"doc={' '.join(doc.split())!r}")
        lines.append(f"    {attr} = {'Many' if end.many else 'One'}({', '.join(args)})")
    return ["", *lines] if lines else []


def _emit_concept(wm, c, m) -> list[str]:
    here, name = m.id, local(c.id)
    base = _type_name(c.extends, wm.concepts[c.extends].module, here) if c.extends else "Entity"
    lines = [
        f"class {name}(*ext({dotted(here)!r}, {name!r}), {base}):",
        f"    {_doc(name, '-', c.id + '.', c.definition)}",
        "",
        f"    WM_ID = {c.id!r}",
        f"    WM_KIND = {c.kind!r}",
    ]
    instances = [i for i in m.individuals if i.instance_of == c.id]
    if instances:
        lines += ["", "    # The model's individuals of this class, set at the end of the module."]
        lines += [f"    {ident(local(i.id))}: ClassVar[{name}]" for i in instances]
    pending = invariants(wm, c)[1]
    if pending:
        lines.append("")
        lines += [f"    # Invariant {i.id} waits for WMX (ADR 0002): {' '.join(i.expr.split())}" for i in pending]
    lines += _relations(wm, c, here)
    checks = _checks(wm, c, here)
    if c.properties or checks:
        every, inherited = all_properties(wm, c), inherited_properties(wm, c)
        lines += _init(wm, here, every, inherited, c.properties, role=False, checks=checks)
        for p in c.properties:
            lines += _getter(wm, p, here)
    return [*lines, "", ""]


def _emit_role(wm, r, here: str) -> list[str]:
    name = local(r.id)
    lines = [
        f"class {name}(*ext({dotted(here)!r}, {name!r}), Role):",
        f"    {_doc(name, 'role -', r.id + '.', r.definition)}",
        "",
        f"    WM_ID = {r.id!r}",
        f"    WM_PLAYED_BY = {(r.played_by or '')!r}",
    ]
    limit = max_per_player(r)
    if limit is not None:
        lines.append(f"    WM_MAX_PER_PLAYER = {limit}")
    lines += _relations(wm, r, here)
    if r.properties:
        lines += _init(wm, here, r.properties, [], r.properties, role=True, checks=[])
        for p in r.properties:
            lines += _getter(wm, p, here)
    return [*lines, "", ""]


def _value(wm, v, here: str) -> str:
    """One of an individual's values as a Python expression."""
    t = v.type
    items = []
    for x in v.items:
        if t.kind == "quantity":
            items.append(f"Quantity({x!r}, {v.prop.unit!r})")
        elif t.kind == "date":
            items.append(f"datetime.date({x.year}, {x.month}, {x.day})")
        elif t.kind == "enum":
            items.append(f"{_type_name(t.target, t.module, here)}.{ident(x)}")
        elif t.kind == "concept":
            cls = individual_class(wm, wm.individuals[x]).id
            items.append(f"{_type_name(cls, module_of(wm, cls), here)}.{ident(local(x))}")
        else:
            items.append(repr(x))
    if not v.many:
        return items[0]
    return "(" + ", ".join(items) + ("," if len(items) == 1 else "") + ")"


def _emit_individuals(wm, m) -> list[str]:
    """``<Class>.<Individual> = <Class>(...)`` for every individual of the module."""
    lines = []
    for ind in module_individuals(wm, m):
        cls = local(individual_class(wm, ind).id)
        if ind.definition:
            lines.append(f"# {' '.join(ind.definition.split())}")
        lines.append(f"{cls}.{ident(local(ind.id))} = {cls}(")
        lines += [f"    {ind.id!r},", f"    {ind.name!r},"]
        lines += [f"    {prop_name(v.prop)}={_value(wm, v, m.id)}," for v in individual_values(wm, ind)]
        lines += [")", ""]
    return ["# --- Individuals: the model's reference instances (L2) ---", "", *lines] if lines else []


def _uses(wm, module, kinds: set[str]) -> bool:
    for owner in [*module.concepts, *module.roles]:
        for p in owner.properties:
            t, card = resolve_type(wm, p), cardinality(p)
            if t.kind in kinds or ("list" in kinds and card.many):
                return True
    return any(v.type.kind in kinds for ind in module.individuals for v in individual_values(wm, ind))


def _module_source(wm, m) -> str:
    here = m.id
    head = [banner("#", m, _EXT_HINT.format(module=dotted(here))), _doc(f"{m.id} {m.version} - {m.title}".strip())]
    head += ["", "from __future__ import annotations", ""]
    if _uses(wm, m, {"date"}):
        head.append("import datetime  # noqa: F401")
    if _uses(wm, m, {"list"}):
        head.append("from collections.abc import Iterable")
    if m.enumerations:
        head.append("from enum import Enum")
    if m.individuals:
        head.append("from typing import ClassVar")
    head.append("")
    for other in referenced_modules(wm, m):
        head.append(f"import wmoop.{dotted(other)} as {_alias(other)}")
    head.append(_KERNEL_IMPORT)
    body = ["", ""]
    for e in m.enumerations:
        body += _emit_enum(e)
    for c in topo_concepts(m, wm):
        body += _emit_concept(wm, c, m)
    for r in m.roles:
        body += _emit_role(wm, r, here)
    body += _emit_individuals(wm, m)
    return "\n".join(head + body).rstrip() + "\n"


def _kernel_source(wm) -> str:
    """The kernel template, then the model's unit catalogue for ``check_quantity`` and ``Quantity.in_``."""
    lines = [banner("#"), template("python", "_kernel.py").rstrip()]
    units, kinds = unit_catalog(wm), kind_dimensions(wm)
    if units:
        lines += [
            "",
            "",
            "# The model's unit catalogue: every wmoop.core/Unit individual, by symbol.",
            "_UNITS.update(",
            "    {",
        ]
        lines += [f"        {u.symbol!r}: ({u.kind!r}, {u.factor!r}, {u.offset!r})," for u in units]
        lines += ["    }", ")"]
    if kinds:
        lines += [
            "",
            "# The SI dimension of every wmoop.core/QuantityKind individual that records one.",
            "_KINDS.update(",
            "    {",
        ]
        lines += [f"        {kind!r}: {dimension!r}," for kind, dimension in kinds.items()]
        lines += ["    }", ")"]
    return "\n".join(lines)


def generate_python(wm, out_dir: str) -> list:
    nested = sorted(m.id for m in wm.modules.values() if len(module_path(m.id)) > 1)
    if nested:
        raise ModelError(f"nested modules are not supported by the Python generator yet: {', '.join(nested)}")
    pkg = os.path.join(out_dir, "wmoop")
    written = [write(os.path.join(pkg, "_kernel.py"), _kernel_source(wm))]
    for m in wm.modules.values():
        written.append(write(os.path.join(pkg, dotted(m.id) + ".py"), _module_source(wm, m)))
    if CORE_MODULE not in wm.modules:
        core = [banner("#"), repr("wmoop.core - the kernel's public names (the model has no wmoop.core module)."), ""]
        core.append(_KERNEL_IMPORT)
        written.append(write(os.path.join(pkg, "core.py"), "\n".join(core)))
    return written
