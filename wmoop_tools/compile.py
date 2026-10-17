"""Validate a loaded :class:`WorldModel` and provide helpers used by generators."""
from __future__ import annotations

from .model import Concept, WorldModel

MAX_INHERITANCE_DEPTH = 6


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
                errors.append("module dependency cycle: " + " -> ".join(stack + [dep]))
            elif s is None:
                dfs(dep, stack + [dep])
        state[node] = "black"

    for mid in graph:
        if state.get(mid) is None:
            dfs(mid, [mid])

    # Inheritance must be acyclic and shallow (Invariant 3).
    for c in wm.concepts.values():
        seen = set()
        cur = c
        depth = 0
        while cur and cur.extends:
            if cur.extends in seen:
                errors.append(f"{c.id}: inheritance cycle")
                break
            seen.add(cur.extends)
            cur = wm.concepts.get(cur.extends)
            depth += 1
            if depth > MAX_INHERITANCE_DEPTH:
                errors.append(f"{c.id}: inheritance depth exceeds {MAX_INHERITANCE_DEPTH}")
                break

    if errors:
        raise ModelError("Model validation failed:\n  - " + "\n  - ".join(errors))
    return wm


def concept_chain(wm: WorldModel, concept: Concept) -> list:
    """Root-first list of ancestors including ``concept`` itself."""
    chain = []
    cur = concept
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
