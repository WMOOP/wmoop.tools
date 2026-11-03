"""Generate the TypeScript binding: one ES module per WML module, under ``wmoop/``.

Layout under ``out_dir`` (a binding's ``generated/``)::

    package.json          ``"type": "module"``: the modules are ES modules
    tsconfig.json         strict settings that check the generated modules on their own, without Node.js types
    wmoop/_kernel.ts      errors, identity, quantities, roles, relation ends and the extension hook
                          (from templates/typescript), plus the model's unit catalogue
    wmoop/core.ts         the wmoop.core module, plus the kernel's public names
    wmoop/<domain>.ts     one per WML module, e.g. wmoop/transport.ts

Names follow docs/03-architecture.md §4.2, as in Python: the module ``wmoop/transport`` holds
``Moped``, and members keep the model's names (``wheelCount``). A constructor takes one object, a
``<Name>Init``: ``id`` and ``name``, then the properties by name, so reordering properties in the model
never breaks a caller. A required slot is a required key. An optional slot may be left out and reads
as ``null``, never as a value that would read as a fact. An enumeration is a frozen object whose values
are the model ids, with a union type of the same name.

The constructor checks what the model states: required slots and ``1..*`` cardinalities, enumeration
values, a quantity's unit against the property's kind, and the simple invariants
(``self.<property> <op> <literal>``). The model's individuals are read-only statics of the class they
instantiate, e.g. ``Planet.Earth`` or ``Unit.Kilometre``.

Behaviour is not generated. A hand-written module of the binding adds it with the kernel's ``extend()``,
and declares its types by augmenting the generated module (the TypeScript generation gap)::

    // src/ext/transport.ts  (hand-written, in the binding)
    declare module "../../generated/wmoop/transport.js" {
      interface Moped {
        describe(): string;
      }
    }
    extend(Moped, { describe() { return `${this.name} ...`; } });

The binding imports its extension modules once, before it uses the classes. The generated modules use
only the language, no Node.js or DOM API, and import each other in the model's dependency order.
"""

from __future__ import annotations

import json
import os
import re

from .. import __version__
from ..compile import ModelError, concept_chain, topo_concepts
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
    template,
    unit_catalog,
    write,
)

_HINT = (
    "Add behaviour with extend() from a module that augments this one (see wmoop_tools/generators/typescript_gen.py)."
)
_PRIMITIVE = {"string": "string", "integer": "number", "decimal": "number", "boolean": "boolean", "date": "Date"}
# Members of Entity / Role, and of every object, that a property or relation end must not hide.
_KERNEL_MEMBERS = frozenset(
    {
        "id",
        "name",
        "roles",
        "isA",
        "addRole",
        "hasRole",
        "getRole",
        "roleType",
        "subject",
        "constructor",
        "toString",
        "toLocaleString",
        "valueOf",
        "hasOwnProperty",
        "isPrototypeOf",
        "propertyIsEnumerable",
        "__proto__",
    }
)
# The statics every class has (a function's own properties, the kernel's metadata), which an individual must not reuse.
_STATICS = frozenset(
    {"prototype", "name", "length", "caller", "arguments", "WM_ID", "WM_KIND", "WM_PLAYED_BY", "WM_MAX_PER_PLAYER"}
)
# The globals a generated module names; a model type of the same name is declared there, so they go through globalThis.
_GLOBALS = frozenset({"Date", "Iterable"})
# The kernel's exports, which wmoop/core re-exports, so a wmoop.core type must not take one of their names.
_KERNEL_EXPORTS = frozenset(
    {
        "WmoopError",
        "Type",
        "ConceptId",
        "Quantity",
        "unitKind",
        "checkQuantity",
        "EntityInit",
        "Entity",
        "Role",
        "relationTarget",
        "Links",
        "extend",
        "required",
        "optional",
        "many",
        "enumeration",
        "oneOf",
        "date",
        "individual",
    }
)
_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_OPERATORS = {"==": "===", "!=": "!=="}


def dotted(module_id: str) -> str:
    """``wmoop.transport`` -> ``transport``: the module's file name under ``wmoop/``."""
    return ".".join(module_path(module_id))


def _alias(module_id: str) -> str:
    """The name a module imports another under: ``_transport``."""
    return "_" + "_".join(module_path(module_id))


def member(name: str) -> str:
    """A model member's TypeScript name: the model's own, renamed when it would hide a kernel member."""
    return name + "Value" if name in _KERNEL_MEMBERS else name


def _string(text: str) -> str:
    """A string literal: JSON's escapes are JavaScript's."""
    return json.dumps(text, ensure_ascii=False)


def _number(value) -> str:
    return repr(value)


def _doc(*parts: str | None) -> str:
    """The text of a one-line doc comment, which must not close the comment early."""
    text = " ".join(" ".join((p or "").split()) for p in parts if p)
    return text.replace("*/", "*\\/")


class _Names:
    """How module ``here`` spells types: its own by name, another module's through its alias, and the
    globals through ``globalThis`` when the module declares a type of the same name."""

    def __init__(self, wm, module) -> None:
        self.wm, self.here = wm, module.id
        own = [local(x.id) for x in (*module.enumerations, *module.concepts, *module.roles)]
        self.shadowed = set(own) & _GLOBALS

    def type(self, qname: str) -> str:
        module_id = module_of(self.wm, qname)
        return local(qname) if module_id == self.here else f"{_alias(module_id)}.{local(qname)}"

    def global_(self, name: str) -> str:
        return f"globalThis.{name}" if name in self.shadowed else name

    def annotation(self, t: TypeRef) -> str:
        if t.kind == "quantity":
            return "wm.Quantity"
        if t.kind == "date":
            return self.global_("Date")
        if t.kind in _PRIMITIVE:
            return _PRIMITIVE[t.kind]
        return self.type(t.target)

    def enum_value(self, qname: str, value: str) -> str:
        """``LicenceCategory.AM``, or ``Grade["A-1"]`` for a value that is not an identifier."""
        owner = self.type(qname)
        return f"{owner}.{value}" if _IDENTIFIER.match(value) else f"{owner}[{_string(value)}]"


def _slot(p) -> tuple[bool, bool, bool]:
    """Whether ``p`` is many-valued, whether a caller may leave it out, and whether it may read as null."""
    card = cardinality(p)
    optional = not card.required or p.default is not None
    nullable = not card.many and not card.required and p.default is None
    return card.many, optional, nullable


def _value_type(wm, p, names: _Names) -> str:
    """What the getter of ``p`` returns."""
    many, _, nullable = _slot(p)
    ann = names.annotation(resolve_type(wm, p))
    if many:
        return f"readonly {ann}[]"
    return f"{ann} | null" if nullable else ann


def _init_field(wm, p, names: _Names) -> list[str]:
    many, optional, _ = _slot(p)
    ann = names.annotation(resolve_type(wm, p))
    typ = f"{names.global_('Iterable')}<{ann}>" if many else ann
    head = f"  readonly {member(p.name)}{'?' if optional else ''}: {typ}"
    return [f"  /** {_doc(p.definition or p.name)} */", head + (" | null;" if optional else ";")]


def _default(wm, p, names: _Names) -> str:
    t, d = resolve_type(wm, p), p.default
    if t.kind == "boolean" and isinstance(d, bool):
        return "true" if d else "false"
    numeric = isinstance(d, (int, float)) and not isinstance(d, bool)
    if t.kind in ("integer", "decimal") and numeric:
        return _number(d)
    if t.kind == "quantity" and numeric:
        return f"new wm.Quantity({_number(d)}, {_string(p.unit)})"
    if t.kind == "string" and isinstance(d, str):
        return _string(d)
    if t.kind == "enum" and isinstance(d, str):
        return names.enum_value(t.target, d)
    raise ModelError(f"{p.id}: unsupported default {d!r} for a {t.kind} property")


def _check(wm, p, names: _Names, value: str) -> str:
    """``value`` as the slot ``p`` holds it: a quantity's unit checked, an enumeration value checked."""
    t, label = resolve_type(wm, p), _string(member(p.name))
    if t.kind == "quantity":  # the unit must be of the property's kind
        return f"wm.checkQuantity({value}, {_string(p.unit)}, {_string(quantity_kind(wm, p))}, {label})"
    if t.kind == "enum":
        return f"wm.oneOf({names.type(t.target)}, {value}, {label})"
    return value


def _store(wm, p, names: _Names) -> str:
    """The constructor statement that checks the slot ``p`` and keeps its value."""
    many, _, nullable = _slot(p)
    name, label = member(p.name), _string(member(p.name))
    given = f"init.{name}"
    converts = resolve_type(wm, p).kind in ("quantity", "enum")
    if many:
        args = [given, label, "true" if cardinality(p).required else "false"]
        if converts:
            args.append(f"(v) => {_check(wm, p, names, 'v')}")
        return f"    this.#{name} = wm.many({', '.join(args)});"
    if p.default is not None:
        return f"    this.#{name} = {_check(wm, p, names, f'{given} ?? {_default(wm, p, names)}')};"
    if not nullable:
        return f"    this.#{name} = {_check(wm, p, names, f'wm.required({given}, {label})')};"
    if converts:
        return f"    this.#{name} = wm.optional({given}, (v) => {_check(wm, p, names, 'v')});"
    return f"    this.#{name} = wm.optional({given});"


def _comparison(c: Clause, subject: str, names: _Names) -> str:
    """A clause of a simple invariant as a TypeScript condition on ``subject``."""
    op = _OPERATORS.get(c.op, c.op)
    if c.type.kind == "quantity":
        return f"{subject}.in({_string(c.prop.unit or '')}) {op} {c.text}"
    if c.type.kind in ("integer", "decimal"):
        return f"{subject} {op} {c.text}"
    if c.type.kind == "boolean":
        return f"{subject} {op} {'true' if c.literal else 'false'}"
    if c.type.kind == "enum":
        return f"{subject} {op} {names.enum_value(c.type.target, str(c.literal))}"
    return f"{subject} {op} {_string(str(c.literal))}"


def _checks(wm, c, names: _Names) -> list[str]:
    """The constructor statements that throw when one of ``c``'s simple invariants does not hold.

    A clause on an absent value holds, as in wmoop.doc's validator: the open world does not know it.
    """
    lines = []
    for check in invariants(wm, c)[0]:
        for clause in check.clauses:
            subject = f"this.{member(clause.prop.name)}"
            guard = f"{subject} !== null && " if _slot(clause.prop)[2] else ""
            lines += [
                f"    if ({guard}!({_comparison(clause, subject, names)})) {{",
                f'      throw new wm.WmoopError("WM-INVARIANT-FAILED", {_string(check.message)});',
                "    }",
            ]
    return lines


def _fields(wm, props: list, names: _Names) -> list[str]:
    return [f"  readonly #{member(p.name)}: {_value_type(wm, p, names)};" for p in props]


def _getters(wm, props: list, names: _Names) -> list[str]:
    lines = []
    for p in props:
        name = member(p.name)
        lines += [
            "",
            f"  /** {_doc(p.definition or p.name)} */",
            f"  get {name}(): {_value_type(wm, p, names)} {{",
            f"    return this.#{name};",
            "  }",
        ]
    return lines


def _relations(wm, holder, names: _Names) -> list[str]:
    """Relation ends: a to-one end is an accessor whose setter keeps the opposite end in step, a
    to-many end a kernel ``Links`` whose add / delete do the same."""
    taken = {member(p.name) for p in holder.properties}
    lines: list[str] = []
    for end in relation_ends(wm, holder):
        name = member(end.name)
        if name in taken:
            raise ModelError(f"{holder.id}: relation end '{end.name}' clashes with another member")
        taken.add(name)
        other = names.type(end.other)
        opposite = member(end.opposite) if end.opposite else None
        doc = f"Inverse of `{end.relation.id}`." if end.inverse else _doc(end.relation.definition or end.name)
        label = _string(name)
        if not end.many:
            lines += [
                "",
                f"  #{name}: {other} | null = null;",
                "",
                f"  /** {doc} */",
                f"  get {name}(): {other} | null {{",
                f"    return this.#{name};",
                "  }",
                "",
                f"  set {name}(value: {other} | null) {{",
            ]
            if opposite is None:
                lines.append(f"    this.#{name} = wm.relationTarget(value, {other}, {label});")
            else:
                lines += [
                    f"    const next = wm.relationTarget(value, {other}, {label});",
                    f"    if (next === this.#{name}) {{",
                    "      return;",
                    "    }",
                    f"    this.#{name}?.{opposite}.drop(this);",
                    f"    this.#{name} = next;",
                    f"    next?.{opposite}.keep(this);",
                ]
            lines.append("  }")
            continue
        if end.inverse and cardinality(end.relation).many:  # the opposite is a to-many end: it links both
            wiring = [f"(item) => item.{opposite}.add(this)", f"(item) => item.{opposite}.delete(this)"]
        elif end.inverse:  # the opposite is a to-one end: its setter updates both
            wiring = [
                f"(item) => {{ item.{opposite} = this; }}",
                f"(item) => {{ if (item.{opposite} === this) item.{opposite} = null; }}",
            ]
        elif opposite:
            wiring = [
                f"(item) => {{ this.{name}.keep(item); item.{opposite}.keep(this); }}",
                f"(item) => {{ this.{name}.drop(item); item.{opposite}.drop(this); }}",
            ]
        else:
            wiring = []
        links = f"wm.Links<{other}>"
        lines += [
            "",
            f"  #{name}: {links} | undefined;",
            "",
            f"  /** {doc} */",
            f"  get {name}(): {links} {{",
            f"    return (this.#{name} ??= new {links}(",
            f"      {other},",
            f"      {label}{',' if wiring else ''}",
            *(f"      {w}{',' if i < len(wiring) - 1 else ''}" for i, w in enumerate(wiring)),
            "    ));",
            "  }",
        ]
    return lines


def _ancestor_individuals(wm, c) -> set[str]:
    return {
        local(i.id) for anc in concept_chain(wm, c)[:-1] for i in wm.individuals.values() if i.instance_of == anc.id
    }


def individual_name(wm, ind) -> str:
    """The static that holds ``ind`` on its class: its local name, or ``<Name>Individual`` if a class
    static, or an ancestor's individual, already has that name."""
    name = local(ind.id)
    if not _IDENTIFIER.match(name):
        raise ModelError(f"{ind.id}: '{name}' is not an identifier, so it cannot name a static")
    taken = _STATICS | _ancestor_individuals(wm, individual_class(wm, ind))
    return f"{name}Individual" if name in taken else name


def _emit_enum(e) -> list[str]:
    name = local(e.id)
    lines = [f"/** {_doc(name, '-', f'`{e.id}`.', e.definition)} */", f"export const {name} = wm.enumeration({{"]
    for v in e.values:
        if v.definition:
            lines.append(f"  /** {_doc(v.definition)} */")
        key = v.id if _IDENTIFIER.match(v.id) else _string(v.id)
        lines.append(f"  {key}: {_string(v.id)},")
    return [
        *lines,
        "});",
        f"/** A value of {{@link {name}}}: one of its model ids. */",
        f"export type {name} = (typeof {name})[keyof typeof {name}];",
        "",
    ]


def _emit_concept(wm, c, m, names: _Names) -> list[str]:
    name = local(c.id)
    base = names.type(c.extends) if c.extends else "wm.Entity"
    own = c.properties
    lines = [f"/** What `new {name}(...)` takes: the properties, by name. */"]
    if own:
        lines.append(f"export interface {name}Init extends {base}Init {{")
        for p in own:
            lines += _init_field(wm, p, names)
        lines.append("}")
    else:
        lines.append(f"export type {name}Init = {base}Init;")
    abstract = "abstract " if c.kind == "abstract" else ""
    lines += [
        "",
        f"/** {_doc(name, '-', f'`{c.id}`.', c.definition)} */",
        f"export {abstract}class {name} extends {base} {{",
        f"  static override readonly WM_ID: string = {_string(c.id)};",
        f"  static override readonly WM_KIND: string = {_string(c.kind)};",
    ]
    instances = [i for i in m.individuals if i.instance_of == c.id]
    if instances:
        lines.append("")
        for ind in instances:
            lines += [
                f"  /** {_doc(ind.definition or ind.name)} Individual `{ind.id}`, set at the end of the module. */",
                f"  declare static readonly {individual_name(wm, ind)}: {name};",
            ]
    pending = invariants(wm, c)[1]
    if pending:
        lines.append("")
        lines += [f"  // Invariant {i.id} waits for WMX (ADR 0002): {' '.join(i.expr.split())}" for i in pending]
    checks = _checks(wm, c, names)
    if own:
        lines += ["", *_fields(wm, own, names)]
    if own or checks:
        lines += ["", f"  constructor(init: {name}Init) {{", "    super(init);"]
        lines += [_store(wm, p, names) for p in own]
        lines += [*checks, "  }"]
    lines += _getters(wm, own, names)
    lines += _relations(wm, c, names)
    return [*lines, "}", ""]


def _emit_role(wm, r, names: _Names) -> list[str]:
    name = local(r.id)
    lines = []
    if r.properties:
        lines.append(f"/** What `new {name}(...)` takes: the properties, by name. */")
        lines.append(f"export interface {name}Init {{")
        for p in r.properties:
            lines += _init_field(wm, p, names)
        lines += ["}", ""]
    lines += [
        f"/** {_doc(name, 'role -', f'`{r.id}`.', r.definition)} */",
        f"export class {name} extends wm.Role {{",
        f"  static override readonly WM_ID: string = {_string(r.id)};",
    ]
    if r.played_by:
        lines.append(f"  static override readonly WM_PLAYED_BY: string = {_string(r.played_by)};")
    limit = max_per_player(r)
    if limit is not None:
        lines.append(f"  static override readonly WM_MAX_PER_PLAYER: number | null = {limit};")
    if r.properties:
        optional = all(_slot(p)[1] for p in r.properties)
        lines += ["", *_fields(wm, r.properties, names), ""]
        lines += [f"  constructor(init: {name}Init{' = {}' if optional else ''}) {{", "    super();"]
        lines += [_store(wm, p, names) for p in r.properties]
        lines.append("  }")
    lines += _getters(wm, r.properties, names)
    lines += _relations(wm, r, names)
    return [*lines, "}", ""]


def _value(wm, v, names: _Names) -> str:
    """One of an individual's values as a TypeScript expression."""
    t = v.type
    items = []
    for x in v.items:
        if t.kind == "quantity":
            items.append(f"new wm.Quantity({_number(x)}, {_string(v.prop.unit)})")
        elif t.kind == "date":
            items.append(f"wm.date({x.year}, {x.month}, {x.day})")
        elif t.kind == "enum":
            items.append(names.enum_value(t.target, x))
        elif t.kind == "concept":
            ref = wm.individuals[x]
            items.append(f"{names.type(individual_class(wm, ref).id)}.{individual_name(wm, ref)}")
        elif t.kind == "boolean":
            items.append("true" if x else "false")
        elif t.kind == "string":
            items.append(_string(x))
        else:  # integer, decimal
            items.append(_number(x))
    return f"[{', '.join(items)}]" if v.many else items[0]


def _emit_individuals(wm, m, names: _Names) -> list[str]:
    """``wm.individual(<Class>, "<Name>", new <Class>({...}))`` for every individual of the module, each
    after the ones it refers to."""
    lines = []
    for ind in module_individuals(wm, m):
        cls = local(individual_class(wm, ind).id)
        if ind.definition:
            lines.append(f"/** {_doc(ind.definition)} */")
        lines += [
            f"wm.individual({cls}, {_string(individual_name(wm, ind))}, new {cls}({{",
            f"  id: {_string(ind.id)},",
            f"  name: {_string(ind.name)},",
        ]
        lines += [f"  {member(v.prop.name)}: {_value(wm, v, names)}," for v in individual_values(wm, ind)]
        lines += ["}));", ""]
    return ["// --- Individuals: the model's reference instances (L2) ---", "", *lines] if lines else []


def _check_names(wm, m) -> None:
    """The module's top-level names must be distinct, and wmoop.core's must leave the kernel's free."""
    names = [local(x.id) for x in (*m.enumerations, *m.concepts, *m.roles)]
    names += [local(c.id) + "Init" for c in m.concepts]
    names += [local(r.id) + "Init" for r in m.roles if r.properties]
    clashes = sorted({n for n in names if names.count(n) > 1})
    if clashes:
        raise ModelError(f"{m.id}: these names are declared twice in the TypeScript module: {', '.join(clashes)}")
    if m.id == CORE_MODULE and _KERNEL_EXPORTS & set(names):
        taken = ", ".join(sorted(_KERNEL_EXPORTS & set(names)))
        raise ModelError(f"{m.id}: {taken} would hide the kernel's export of the same name in wmoop/core")


def _module_source(wm, m) -> str:
    _check_names(wm, m)
    names = _Names(wm, m)
    about = f"{m.id} {m.version}" + (f" - {m.title}" if m.title else "")
    head = [banner("//", m, _HINT), "/**", f" * {_doc(about)}", " *", " * @module", " */", ""]
    if m.enumerations or m.concepts or m.roles:
        head.append('import * as wm from "./_kernel.js";')
    head += [f'import * as {_alias(o)} from "./{dotted(o)}.js";' for o in referenced_modules(wm, m)]
    if m.id == CORE_MODULE:
        head += [
            "",
            "// The kernel's public names: a consumer imports them from wmoop/core.",
            'export * from "./_kernel.js";',
        ]
    body = [""]
    for e in m.enumerations:
        body += _emit_enum(e)
    for c in topo_concepts(m, wm):
        body += _emit_concept(wm, c, m, names)
    for r in m.roles:
        body += _emit_role(wm, r, names)
    body += _emit_individuals(wm, m, names)
    return "\n".join(head + body).rstrip() + "\n"


def _kernel_source(wm) -> str:
    """The kernel template, then the model's unit catalogue for ``checkQuantity`` and ``Quantity.in``."""
    lines = [banner("//"), template("typescript", "_kernel.ts").rstrip()]
    units, kinds = unit_catalog(wm), kind_dimensions(wm)
    if units:
        lines += ["", "// The model's unit catalogue: every wmoop.core/Unit individual, by symbol."]
        lines += [
            f"UNITS.set({_string(u.symbol)}, [{_string(u.kind)}, {_number(u.factor)}, {_number(u.offset)}]);"
            for u in units
        ]
    if kinds:
        lines += ["", "// The SI dimension of every wmoop.core/QuantityKind individual that records one."]
        lines += [f"KINDS.set({_string(kind)}, {_string(' '.join(map(str, d)))});" for kind, d in kinds.items()]
    return "\n".join(lines)


def _tsconfig() -> str:
    """Strict settings that check the generated modules on their own (``tsc -p generated``), with no
    Node.js types, so they stay free of any runtime but the language. A binding compiles them with its
    own tsconfig.json."""
    options = {
        "target": "es2022",
        "lib": ["es2022"],
        "module": "nodenext",
        "types": [],
        "strict": True,
        "exactOptionalPropertyTypes": True,
        "noImplicitOverride": True,
        "noUncheckedIndexedAccess": True,
        "noUnusedLocals": True,
        "noUnusedParameters": True,
        "verbatimModuleSyntax": True,
        "erasableSyntaxOnly": True,
        "noEmit": True,
    }
    text = json.dumps({"compilerOptions": options, "include": ["wmoop"]}, indent=2)
    hint = "Checks the generated modules on their own: tsc -p generated. A binding compiles them with its own tsconfig."
    return banner("//", hint=hint) + "\n" + text


def _package_json() -> str:
    """Marks the modules as ES modules, for TypeScript's ``nodenext`` resolution and for Node.js."""
    note = f"Generated by wmoop.tools {__version__}. DO NOT EDIT: changes are overwritten by the next regeneration."
    return json.dumps({"//": note, "private": True, "type": "module"}, indent=2)


def generate_typescript(wm, out_dir: str) -> list:
    nested = sorted(m.id for m in wm.modules.values() if len(module_path(m.id)) > 1)
    if nested:
        raise ModelError(f"nested modules are not supported by the TypeScript generator yet: {', '.join(nested)}")
    pkg = os.path.join(out_dir, "wmoop")
    written = [
        write(os.path.join(out_dir, "package.json"), _package_json()),
        write(os.path.join(out_dir, "tsconfig.json"), _tsconfig()),
        write(os.path.join(pkg, "_kernel.ts"), _kernel_source(wm)),
    ]
    for m in wm.modules.values():
        written.append(write(os.path.join(pkg, dotted(m.id) + ".ts"), _module_source(wm, m)))
    if CORE_MODULE not in wm.modules:
        core = [
            banner("//"),
            "/**",
            " * wmoop.core - the kernel's public names (the model has no wmoop.core module).",
            " *",
            " * @module",
            " */",
            "",
            'export * from "./_kernel.js";',
        ]
        written.append(write(os.path.join(pkg, "core.ts"), "\n".join(core)))
    return written
