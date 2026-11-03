"""Validate a loaded :class:`WorldModel` and provide helpers used by generators."""

from __future__ import annotations

from .model import Concept, WorldModel

MAX_INHERITANCE_DEPTH = 6
# The wmoop.core concepts whose individuals are the QuantityKind / Unit catalogue (R5).
QUANTITY_KIND = "wmoop.core/QuantityKind"
UNIT = "wmoop.core/Unit"


class ModelError(Exception):
    pass


def validate(wm: WorldModel) -> WorldModel:
    """Enforce the structural invariants. Raises :class:`ModelError` on any violation."""
    errors: list[str] = []

    for c in wm.concepts.values():
        if c.extends and c.extends not in wm.concepts:
            errors.append(f"{c.id}: extends unknown concept '{c.extends}'")
    for r in wm.roles.values():
        if r.played_by and r.played_by not in wm.concepts:
            errors.append(f"{r.id}: played_by unknown concept '{r.played_by}'")
    errors += _relation_errors(wm)

    # Module dependency graph must be acyclic (Invariant 5). External deps
    # (modules not in this model, e.g. wmoop.core) are ignored.
    graph = {m.id: [d for d in m.depends_on if d] for m in wm.modules.values()}
    state: dict[str, str] = {}

    def dfs(node: str, stack: list[str]) -> None:
        state[node] = "grey"
        for dep in graph.get(node, []):
            if dep not in wm.modules:
                continue
            s = state.get(dep)
            if s == "grey":
                errors.append("module dependency cycle: " + " -> ".join([*stack, dep]))
            elif s is None:
                dfs(dep, [*stack, dep])
        state[node] = "black"

    for mid in graph:
        if state.get(mid) is None:
            dfs(mid, [mid])

    # Inheritance must be acyclic and shallow (Invariant 3).
    cyclic = False
    for c in wm.concepts.values():
        seen = set()
        cur = c
        depth = 0
        while cur and cur.extends:
            if cur.extends in seen:
                errors.append(f"{c.id}: inheritance cycle")
                cyclic = True
                break
            seen.add(cur.extends)
            cur = wm.concepts.get(cur.extends)
            depth += 1
            if depth > MAX_INHERITANCE_DEPTH:
                errors.append(f"{c.id}: inheritance depth exceeds {MAX_INHERITANCE_DEPTH}")
                break

    errors += _unit_errors(wm)
    if not cyclic:  # both walk the inheritance chain
        errors += _individual_errors(wm)

    if errors:
        raise ModelError("Model validation failed:\n  - " + "\n  - ".join(errors))
    return wm


def _relation_errors(wm: WorldModel) -> list[str]:
    """Targets resolve; an inverse is declared on the relation's target, under a free member name."""
    errors: list[str] = []
    members: dict[str, set[str]] = {}
    for owner in [*wm.concepts.values(), *wm.roles.values()]:
        members.setdefault(owner.id, set()).update(p.name for p in owner.properties)
        members[owner.id].update(r.name for r in owner.relations)
    for owner in [*wm.concepts.values(), *wm.roles.values()]:
        for r in owner.relations:
            if r.target not in wm.concepts and r.target not in wm.roles:
                errors.append(f"{r.id}: relation target '{r.target}' is not a concept or role")
                continue
            if not r.inverse:
                continue
            on, _, name = r.inverse.partition("#")
            if on != r.target or not name:
                errors.append(f"{r.id}: inverse '{r.inverse}' must be a member of the target, {r.target}#<name>")
            elif name in members.setdefault(on, set()):
                errors.append(f"{r.id}: inverse '{r.inverse}' clashes with a member {on} already has")
            else:
                members[on].add(name)
    return errors


def _unit_errors(wm: WorldModel) -> list[str]:
    """R5, once the model has a unit catalogue: a unit is a catalogue symbol, of the slot's QuantityKind."""
    kinds = {i.id for i in wm.individuals.values() if i.instance_of == QUANTITY_KIND}
    units = {
        i.values.get("symbol"): i.values.get("quantityKind") for i in wm.individuals.values() if i.instance_of == UNIT
    }
    if not units:
        return []  # no catalogue (e.g. a model without wmoop.core): units cannot be checked
    errors: list[str] = []
    for owner in [*wm.concepts.values(), *wm.roles.values()]:
        for p in owner.properties:
            if p.unit is None:
                if p.type in kinds:
                    errors.append(f"{p.id}: a quantity of kind {p.type} needs a unit")
            elif p.unit not in units:
                errors.append(f"{p.id}: unit '{p.unit}' is not in the unit catalogue")
            elif p.type in kinds and units[p.unit] != p.type:
                errors.append(f"{p.id}: unit '{p.unit}' measures {units[p.unit]}, not {p.type}")
    return errors


def _individual_errors(wm: WorldModel) -> list[str]:
    """An individual instantiates a concrete concept, sets only its properties and every required one."""
    errors: list[str] = []
    for ind in wm.individuals.values():
        c = wm.concepts.get(ind.instance_of)
        if c is None:
            errors.append(f"{ind.id}: instance_of unknown concept '{ind.instance_of}'")
            continue
        if c.kind == "abstract":
            errors.append(f"{ind.id}: instantiates abstract concept '{c.id}'")
        props = {p.name: p for p in all_properties(wm, c)}
        errors += [
            f"{ind.id}: '{key}' is not a property of '{c.id}' or its ancestors"
            for key in ind.values
            if key not in props
        ]
        for name, p in props.items():
            lower = str(p.cardinality or "0..1").partition("..")[0]
            required = p.required or (lower.isdigit() and int(lower) >= 1)
            if required and p.default is None and name not in ind.values:
                errors.append(f"{ind.id}: no value for required property '{p.id}'")
    return errors


def concept_chain(wm: WorldModel, concept: Concept) -> list:
    """Root-first list of ancestors including ``concept`` itself."""
    chain = []
    cur: Concept | None = concept
    while cur:
        chain.append(cur)
        cur = wm.concepts.get(cur.extends) if cur.extends else None
    chain.reverse()
    return chain


def inherited_properties(wm: WorldModel, concept: Concept) -> list:
    props = []
    for anc in concept_chain(wm, concept)[:-1]:
        props.extend(anc.properties)
    return props


def all_properties(wm: WorldModel, concept: Concept) -> list:
    props = []
    for anc in concept_chain(wm, concept):
        props.extend(anc.properties)
    return props


def topo_concepts(module, wm: WorldModel) -> list:
    """Order a module's concepts so a base class is emitted before its subclasses."""
    local_ids = {c.id for c in module.concepts}
    placed: set = set()
    out = []
    remaining = list(module.concepts)
    changed = True
    while remaining and changed:
        changed = False
        for c in list(remaining):
            if (not c.extends) or (c.extends not in local_ids) or (c.extends in placed):
                out.append(c)
                placed.add(c.id)
                remaining.remove(c)
                changed = True
    out.extend(remaining)
    return out
