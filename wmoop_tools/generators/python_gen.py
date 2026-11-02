"""Generate the Python binding: one module per WML module, in the ``wmoop`` namespace package.

Layout under ``out_dir`` (a binding's ``generated/``)::

    wmoop/_kernel.py      identity, quantities, roles and the extension hook (from templates/python)
    wmoop/core.py         the wmoop.core module, plus the kernel's public names
    wmoop/<domain>.py     one per WML module, e.g. wmoop/transport.py

``wmoop`` has no ``__init__.py`` (a PEP 420 namespace package), so per-domain distributions and a
binding's hand-written packages can share it.

Names follow docs/03-architecture.md §4.2: ``wmoop.transport.Moped``, ``wheel_count``. A constructor
takes ``id`` and ``name``, then every property as a keyword argument, so reordering properties in the
model never breaks a caller. Required slots have no default; an optional slot defaults to ``None``,
never to a value that would read as a fact.

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
    TypeRef,
    banner,
    cardinality,
    local,
    module_of,
    module_path,
    referenced_modules,
    relation_ends,
    resolve_type,
    snake,
    template,
    write,
)

# Members of Entity / Role that a property must not shadow.
_KERNEL_MEMBERS = frozenset({"id", "name", "roles", "is_a", "add_role", "has_role", "get_role", "role_type", "subject"})
_PRIMITIVE = {"string": "str", "integer": "int", "decimal": "float", "boolean": "bool", "date": "datetime.date"}
_KERNEL_IMPORT = "from wmoop._kernel import ConceptId, Entity, Many, One, Quantity, Role, ext  # noqa: F401"
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


def _default_literal(p) -> str:
    d = p.default
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
        return f"{name}: {ann} = {_default_literal(p)}"
    if card.required:
        return f"{name}: {ann}"
    return f"{name}: {ann} | None = None"


def _store(wm, p, here: str) -> list[str]:
    t, card = resolve_type(wm, p), cardinality(p)
    # The escaped name keeps a model property `name` (stored as `_wm_name_`) off the kernel's `_wm_name`.
    name = prop_name(p)
    attr = f"self._wm_{name}"
    enum = _annotation(t, here) if t.kind == "enum" else None
    if card.many:
        items = f"tuple({enum}(v) for v in {name})" if enum else f"tuple({name})"
        lines = [f"        {attr} = {items}"]
        if card.required:
            lines += [f"        if not {attr}:", f'            raise ValueError("{name} needs at least one value.")']
        return lines
    lines = []
    if card.required and p.default is None:
        lines += [f"        if {name} is None:", f'            raise ValueError("{name} is required.")']
    if enum and (card.required or p.default is not None):
        value = f"{enum}({name})"
    elif enum:
        value = f"None if {name} is None else {enum}({name})"
    else:
        value = name
    return [*lines, f"        {attr} = {value}"]


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


def _init(wm, here: str, every: list, inherited: list, own: list, *, role: bool) -> list[str]:
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
    return lines


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


def _emit_concept(wm, c, here: str) -> list[str]:
    name = local(c.id)
    base = _type_name(c.extends, wm.concepts[c.extends].module, here) if c.extends else "Entity"
    lines = [
        f"class {name}(*ext({dotted(here)!r}, {name!r}), {base}):",
        f"    {_doc(name, '-', c.id + '.', c.definition)}",
        "",
        f"    WM_ID = {c.id!r}",
        f"    WM_KIND = {c.kind!r}",
        *_relations(wm, c, here),
    ]
    if c.properties:
        lines += _init(wm, here, all_properties(wm, c), inherited_properties(wm, c), c.properties, role=False)
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
        *_relations(wm, r, here),
    ]
    if r.properties:
        lines += _init(wm, here, r.properties, [], r.properties, role=True)
        for p in r.properties:
            lines += _getter(wm, p, here)
    return [*lines, "", ""]


def _uses(wm, module, kinds: set[str]) -> bool:
    for owner in [*module.concepts, *module.roles]:
        for p in owner.properties:
            t, card = resolve_type(wm, p), cardinality(p)
            if t.kind in kinds or ("list" in kinds and card.many):
                return True
    return False


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
    head.append("")
    for other in referenced_modules(wm, m):
        head.append(f"import wmoop.{dotted(other)} as {_alias(other)}")
    head.append(_KERNEL_IMPORT)
    body = ["", ""]
    for e in m.enumerations:
        body += _emit_enum(e)
    for c in topo_concepts(m, wm):
        body += _emit_concept(wm, c, here)
    for r in m.roles:
        body += _emit_role(wm, r, here)
    return "\n".join(head + body).rstrip() + "\n"


def generate_python(wm, out_dir: str) -> list:
    nested = sorted(m.id for m in wm.modules.values() if len(module_path(m.id)) > 1)
    if nested:
        raise ModelError(f"nested modules are not supported by the Python generator yet: {', '.join(nested)}")
    pkg = os.path.join(out_dir, "wmoop")
    written = [write(os.path.join(pkg, "_kernel.py"), banner("#") + "\n" + template("python", "_kernel.py"))]
    for m in wm.modules.values():
        written.append(write(os.path.join(pkg, dotted(m.id) + ".py"), _module_source(wm, m)))
    if CORE_MODULE not in wm.modules:
        core = [banner("#"), repr("wmoop.core - the kernel's public names (the model has no wmoop.core module)."), ""]
        core.append("from wmoop._kernel import ConceptId, Entity, Quantity, Role  # noqa: F401")
        written.append(write(os.path.join(pkg, "core.py"), "\n".join(core)))
    return written
