"""Generate the C# binding: one project per WML module, every type a ``partial`` class.

Layout under ``out_dir`` (a binding's ``generated/``)::

    Wmoop.Generated.sln               every project below, so a new module builds with no manual edit
    Wmoop.Core/Wmoop.Core.csproj      the kernel (ConceptId, Quantity, Entity, Role) + the wmoop.core module
    Wmoop.Core/Kernel.Gen.cs          from templates/csharp/Kernel.cs
    Wmoop.Transport/Wmoop.Transport.csproj
    Wmoop.Transport/Moped.Gen.cs      one file per type
    ...

Names follow docs/03-architecture.md §4.2: ``Wmoop.Transport.Moped``, ``WheelCount``. Objects are built
with object initializers over ``required`` / ``init`` properties, so reordering properties in the model
never breaks a caller. An optional slot is nullable, never a default that would read as a fact (§6.5).

Behaviour is not generated. Every type is ``partial`` (docs/03-architecture.md §2.2), and each project
also compiles ``$(WmoopSourceRoot)/<Project>/**/*.cs``, the hand-written halves, when the binding sets
``WmoopSourceRoot`` (typically in its ``Directory.Build.props``).
"""

from __future__ import annotations

import os
import uuid

from .. import __version__
from ..compile import ModelError
from .common import (
    CORE_MODULE,
    TypeRef,
    banner,
    cardinality,
    local,
    module_of,
    module_path,
    pascal,
    referenced_modules,
    relation_ends,
    resolve_type,
    template,
    write,
)

_KERNEL = "global::Wmoop.Core"
_KERNEL_PROJECT = "Wmoop.Core"
_SOLUTION = "Wmoop.Generated.sln"
_CSHARP_PROJECT_TYPE = "FAE04EC0-301F-11D3-BF4B-00C04F79EFBC"
_HINT = "Add behaviour in a partial class under $(WmoopSourceRoot)/{project}/."
_PRIMITIVE = {"string": "string", "integer": "long", "decimal": "double", "boolean": "bool", "date": "DateOnly"}
# Members of Entity / Role (and object) that a generated property must not hide.
_KERNEL_MEMBERS = frozenset(
    {
        "Id",
        "Name",
        "Roles",
        "AddRole",
        "HasRole",
        "GetRole",
        "IsA",
        "RoleType",
        "PlayedBy",
        "Subject",
        "WmId",
        "WmPlayedBy",
        "ToString",
        "Equals",
        "GetHashCode",
        "GetType",
    }
)
# Reserved C# keywords cannot be bare identifiers; an enum member `default` is emitted as `@default`.
_KEYWORDS = frozenset(
    [
        "abstract",
        "as",
        "base",
        "bool",
        "break",
        "byte",
        "case",
        "catch",
        "char",
        "checked",
        "class",
        "const",
        "continue",
        "decimal",
        "default",
        "delegate",
        "do",
        "double",
        "else",
        "enum",
        "event",
        "explicit",
        "extern",
        "false",
        "finally",
        "fixed",
        "float",
        "for",
        "foreach",
        "goto",
        "if",
        "implicit",
        "in",
        "int",
        "interface",
        "internal",
        "is",
        "lock",
        "long",
        "namespace",
        "new",
        "null",
        "object",
        "operator",
        "out",
        "override",
        "params",
        "private",
        "protected",
        "public",
        "readonly",
        "ref",
        "return",
        "sbyte",
        "sealed",
        "short",
        "sizeof",
        "stackalloc",
        "static",
        "string",
        "struct",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "uint",
        "ulong",
        "unchecked",
        "unsafe",
        "ushort",
        "using",
        "virtual",
        "void",
        "volatile",
        "while",
    ]
)


def ident(name: str) -> str:
    """Escape a C# reserved keyword so it is a valid identifier."""
    return "@" + name if name in _KEYWORDS else name


def project(module_id: str) -> str:
    """``wmoop.transport`` -> ``Wmoop.Transport``: the project, assembly and namespace (§4.2)."""
    return "Wmoop." + ".".join(pascal(s) for s in module_path(module_id))


def member(p, owner: str) -> str:
    """The C# property name: PascalCase, renamed when it would clash with its class or the kernel."""
    return member_name(p.name, owner)


def member_name(model_name: str, owner: str) -> str:
    name = pascal(model_name)
    return name + "Value" if name == owner or name in _KERNEL_MEMBERS else name


def _xml(text: str | None) -> str:
    return " ".join((text or "").split()).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _type_name(qname: str, module_id: str, here: str) -> str:
    name = local(qname)
    return name if module_id == here else f"global::{project(module_id)}.{name}"


def _item_type(t: TypeRef, here: str) -> str:
    if t.kind == "quantity":
        return f"{_KERNEL}.Quantity"
    if t.kind in _PRIMITIVE:
        return _PRIMITIVE[t.kind]
    return _type_name(t.target, t.module, here)


def _literal(p, t: TypeRef, item: str) -> str:
    d = p.default
    if t.kind == "boolean" and isinstance(d, bool):
        return "true" if d else "false"
    if t.kind in ("integer", "decimal") and isinstance(d, (int, float)) and not isinstance(d, bool):
        return repr(d)
    if t.kind == "string" and isinstance(d, str):
        return '"' + d.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if t.kind == "enum" and isinstance(d, str):
        return f"{item}.{ident(d)}"
    raise ModelError(f"{p.id}: unsupported default {d!r} for a {t.kind} property")


def _property(wm, p, owner: str, here: str) -> list[str]:
    t, card = resolve_type(wm, p), cardinality(p)
    item = _item_type(t, here)
    name = member(p, owner)
    doc = f"    /// <summary>{_xml(p.definition or p.name)}</summary>"
    if card.many:
        typ = f"IReadOnlyList<{item}>"
        if not card.required:
            return ["", doc, f"    public {typ} {name} {{ get; init; }} = Array.Empty<{item}>();"]
        field = f"_wm{name}"
        return [
            "",
            f"    private {typ} {field} = Array.Empty<{item}>();",
            "",
            doc,
            f"    public required {typ} {name}",
            "    {",
            f"        get => {field};",
            f"        init => {field} = value is {{ Count: > 0 }}",
            "            ? value",
            f'            : throw new ArgumentException("{name} needs at least one value.", nameof({name}));',
            "    }",
        ]
    if p.default is not None:
        return ["", doc, f"    public {item} {name} {{ get; init; }} = {_literal(p, t, item)};"]
    if card.required:
        return ["", doc, f"    public required {item} {name} {{ get; init; }}"]
    return ["", doc, f"    public {item}? {name} {{ get; init; }}"]


def _head(m) -> list[str]:
    ns = project(m.id)
    return [
        banner("//", m, _HINT.format(project=ns)),
        "#nullable enable",
        "using System;",
        "using System.Collections.Generic;",
        "",
        f"namespace {ns};",
        "",
    ]


def _enum_source(e, m) -> str:
    name = local(e.id)
    lines = [*_head(m), f"/// <summary>{name} - <c>{e.id}</c>. {_xml(e.definition)}</summary>", f"public enum {name}"]
    lines.append("{")
    for v in e.values:
        if v.definition:
            lines.append(f"    /// <summary>{_xml(v.definition)}</summary>")
        lines.append(f"    {ident(v.id)},")
    return "\n".join([*lines, "}"])


def _relations(wm, holder, owner: str, here: str) -> list[str]:
    """Relation ends: a to-one end is a property whose setter keeps the opposite end in step, a
    to-many end a kernel ``Links<T>`` whose Add / Remove do the same."""
    taken = {member(p, owner) for p in holder.properties}
    lines: list[str] = []
    for end in relation_ends(wm, holder):
        name = member_name(end.name, owner)
        if name in taken:
            raise ModelError(f"{holder.id}: relation end '{end.name}' clashes with another member")
        taken.add(name)
        other = _type_name(end.other, module_of(wm, end.other), here)
        opposite = member_name(end.opposite, local(end.other)) if end.opposite else None
        doc = f"Inverse of <c>{end.relation.id}</c>." if end.inverse else _xml(end.relation.definition or end.name)
        field = f"_wm{name}"
        if not end.many:
            lines += ["", f"    /// <summary>{doc}</summary>"]
            if opposite is None:
                lines.append(f"    public {other}? {name} {{ get; set; }}")
                continue
            lines += [
                f"    public {other}? {name}",
                "    {",
                f"        get => {field};",
                "        set",
                "        {",
                f"            if (ReferenceEquals({field}, value))",
                "                return;",
                f"            {field}?.{opposite}.Drop(this);",
                f"            {field} = value;",
                f"            value?.{opposite}.Keep(this);",
                "        }",
                "    }",
                "",
                f"    private {other}? {field};",
            ]
            continue
        links = f"{_KERNEL}.Links<{other}>"
        if end.inverse and cardinality(end.relation).many:
            wiring = [f"item => item.{opposite}.Add(this),", f"item => item.{opposite}.Remove(this));"]
        elif end.inverse:
            wiring = [
                f"item => item.{opposite} = this,",
                f"item => {{ if (ReferenceEquals(item.{opposite}, this)) item.{opposite} = null; }});",
            ]
        elif opposite:
            wiring = [
                f"item => {{ {name}.Keep(item); item.{opposite}.Keep(this); }},",
                f"item => {{ {name}.Drop(item); item.{opposite}.Drop(this); }});",
            ]
        else:
            wiring = [f"item => {name}.Keep(item),", f"item => {name}.Drop(item));"]
        lines += [
            "",
            f"    /// <summary>{doc}</summary>",
            f"    public {links} {name} => {field} ??= new(",
            *(f"        {w}" for w in wiring),
            "",
            f"    private {links}? {field};",
        ]
    return lines


def _concept_source(wm, c, m) -> str:
    here, name = m.id, local(c.id)
    base = _type_name(c.extends, wm.concepts[c.extends].module, here) if c.extends else f"{_KERNEL}.Entity"
    kind = "abstract partial class" if c.kind == "abstract" else "partial class"
    hides = "new " if c.extends else ""
    lines = [
        *_head(m),
        f"/// <summary>{name} - <c>{c.id}</c>. {_xml(c.definition)}</summary>",
        f"public {kind} {name} : {base}",
        "{",
        f'    public {hides}const string WmId = "{c.id}";',
    ]
    for p in c.properties:
        lines += _property(wm, p, name, here)
    lines += _relations(wm, c, name, here)
    return "\n".join([*lines, "}"])


def _role_source(wm, r, m) -> str:
    here, name = m.id, local(r.id)
    lines = [
        *_head(m),
        f"/// <summary>{name} role - <c>{r.id}</c>. {_xml(r.definition)}</summary>",
        f"public partial class {name} : {_KERNEL}.Role",
        "{",
        f'    public const string WmId = "{r.id}";',
    ]
    if r.played_by:
        lines.append(f'    public const string WmPlayedBy = "{r.played_by}";')
    lines += ["", f"    public override {_KERNEL}.ConceptId RoleType => WmId;"]
    if r.played_by:
        lines.append("    public override string PlayedBy => WmPlayedBy;")
    for p in r.properties:
        lines += _property(wm, p, name, here)
    lines += _relations(wm, r, name, here)
    return "\n".join([*lines, "}"])


def _csproj(name: str, version: str, references: list[str], module=None) -> str:
    lines = [
        '<Project Sdk="Microsoft.NET.Sdk">',
        "",
        "  <!--",
        banner("   ", module, _HINT.format(project=name)),
        "  -->",
        "  <PropertyGroup>",
        "    <TargetFramework>net8.0</TargetFramework>",
        "    <Nullable>enable</Nullable>",
        "    <ImplicitUsings>disable</ImplicitUsings>",
        f"    <RootNamespace>{name}</RootNamespace>",
        f"    <AssemblyName>{name}</AssemblyName>",
        f"    <Version>{version}</Version>",
        "  </PropertyGroup>",
    ]
    if references:
        lines += ["", "  <ItemGroup>"]
        lines += [f'    <ProjectReference Include="../{ref}/{ref}.csproj" />' for ref in references]
        lines.append("  </ItemGroup>")
    own = f"$(WmoopSourceRoot)/{name}"
    lines += [
        "",
        "  <!-- The hand-written halves of the partial classes, when the binding sets WmoopSourceRoot. -->",
        "  <ItemGroup Condition=\"'$(WmoopSourceRoot)' != ''\">",
        f'    <Compile Include="{own}/**/*.cs" Exclude="{own}/bin/**;{own}/obj/**" />',
        "  </ItemGroup>",
        "",
        "</Project>",
    ]
    return "\n".join(lines)


def _guid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/WMOOP/{name}")).upper()


def _solution(projects: list[str]) -> str:
    lines = [
        "",
        "Microsoft Visual Studio Solution File, Format Version 12.00",
        "# Visual Studio Version 17",
        "VisualStudioVersion = 17.0.31903.59",
        "MinimumVisualStudioVersion = 10.0.40219.1",
    ]
    for p in projects:
        lines += [f'Project("{{{_CSHARP_PROJECT_TYPE}}}") = "{p}", "{p}\\{p}.csproj", "{{{_guid(p)}}}"', "EndProject"]
    lines += [
        "Global",
        "\tGlobalSection(SolutionConfigurationPlatforms) = preSolution",
        "\t\tDebug|Any CPU = Debug|Any CPU",
        "\t\tRelease|Any CPU = Release|Any CPU",
        "\tEndGlobalSection",
        "\tGlobalSection(ProjectConfigurationPlatforms) = postSolution",
    ]
    for p in projects:
        for cfg in ("Debug", "Release"):
            lines += [
                f"\t\t{{{_guid(p)}}}.{cfg}|Any CPU.ActiveCfg = {cfg}|Any CPU",
                f"\t\t{{{_guid(p)}}}.{cfg}|Any CPU.Build.0 = {cfg}|Any CPU",
            ]
    return "\n".join([*lines, "\tEndGlobalSection", "EndGlobal"])


def generate_csharp(wm, out_dir: str) -> list:
    written: list[str] = []
    core = wm.modules.get(CORE_MODULE)
    kernel = os.path.join(out_dir, _KERNEL_PROJECT, "Kernel.Gen.cs")
    written.append(write(kernel, banner("//", core) + "\n" + template("csharp", "Kernel.cs")))
    projects = [_KERNEL_PROJECT]
    if core is None:
        written.append(
            write(
                os.path.join(out_dir, _KERNEL_PROJECT, f"{_KERNEL_PROJECT}.csproj"),
                _csproj(_KERNEL_PROJECT, __version__, []),
            )
        )

    for m in wm.modules.values():
        name = project(m.id)
        folder = os.path.join(out_dir, name)
        sources: dict[str, str] = {}
        for e in m.enumerations:
            sources[local(e.id)] = _enum_source(e, m)
        for c in m.concepts:
            sources[local(c.id)] = _concept_source(wm, c, m)
        for r in m.roles:
            sources[local(r.id)] = _role_source(wm, r, m)
        if len(sources) != len(m.enumerations) + len(m.concepts) + len(m.roles):
            raise ModelError(f"{m.id}: two types share a name")
        for type_name, source in sorted(sources.items()):
            written.append(write(os.path.join(folder, f"{type_name}.Gen.cs"), source))

        deps = {d for d in m.depends_on if d in wm.modules} | set(referenced_modules(wm, m))
        refs = sorted(project(d) for d in deps - {m.id, CORE_MODULE})
        if m.id != CORE_MODULE:
            refs.insert(0, _KERNEL_PROJECT)
        written.append(write(os.path.join(folder, f"{name}.csproj"), _csproj(name, m.version, refs, m)))
        if m.id != CORE_MODULE:
            projects.append(name)

    written.append(write(os.path.join(out_dir, _SOLUTION), _solution(projects)))
    return written
