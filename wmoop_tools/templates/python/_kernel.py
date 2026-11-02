"""The runtime kernel every generated WMOOP module imports: identity, quantities, roles, extensions.

``wmoop.core`` re-exports the public names, so a consumer writes ``from wmoop.core import Quantity``.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TypeVar


@dataclass(frozen=True)
class ConceptId:
    """A stable WMOOP identifier, e.g. ``wmoop.transport/Moped`` or an individual's own id."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("A ConceptId must be a non-empty identifier.")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Quantity:
    """A value with its unit; a measurable property is never a bare number."""

    value: float
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("A Quantity must carry a unit.")

    def __str__(self) -> str:
        v = self.value
        text = str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
        return f"{text} {self.unit}"


R = TypeVar("R", bound="Role")


class Entity:
    """Base of every generated concept: identity, name, and the roles it plays.

    A class whose own ``WM_KIND`` is ``"abstract"`` cannot be instantiated; a hand-written subclass can.
    """

    WM_ID = ""
    WM_KIND = "abstract"

    def __init__(self, id: ConceptId | str, name: str) -> None:
        if vars(type(self)).get("WM_KIND") == "abstract":
            raise TypeError(f"{type(self).__name__} is abstract and cannot be instantiated directly.")
        self._wm_id = id if isinstance(id, ConceptId) else ConceptId(id)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("An entity needs a non-empty name.")
        self._wm_name = name
        self._wm_roles: list[Role] = []

    @property
    def id(self) -> ConceptId:
        return self._wm_id

    @property
    def name(self) -> str:
        return self._wm_name

    @property
    def roles(self) -> tuple[Role, ...]:
        return tuple(self._wm_roles)

    def is_a(self, qname: str) -> bool:
        """True when this entity's class, or one of its ancestors, is the model type ``qname``."""
        return any(vars(k).get("WM_ID") == qname for k in type(self).__mro__)

    def add_role(self, role: R) -> R:
        """Attach ``role`` by composition; the role's ``played_by`` type must be one of this entity's types."""
        played_by = type(role).WM_PLAYED_BY
        if played_by and not self.is_a(played_by):
            raise TypeError(f"{type(role).__name__} is played by {played_by}, which {type(self).__name__} is not.")
        role._wm_attach(self)
        self._wm_roles.append(role)
        return role

    def has_role(self, role_type: type[Role]) -> bool:
        return self.get_role(role_type) is not None

    def get_role(self, role_type: type[R]) -> R | None:
        for r in self._wm_roles:
            if isinstance(r, role_type):
                return r
        return None

    def __str__(self) -> str:
        return f"{self._wm_name} [{self._wm_id}]"


class Role:
    """Base of every generated role: a facet an entity plays, attached by composition."""

    WM_ID = ""
    WM_PLAYED_BY = ""

    def __init__(self) -> None:
        self._wm_subject: Entity | None = None

    @property
    def role_type(self) -> ConceptId:
        return ConceptId(type(self).WM_ID)

    @property
    def subject(self) -> Entity | None:
        return self._wm_subject

    def _wm_attach(self, subject: Entity) -> None:
        if self._wm_subject is not None:
            raise RuntimeError("Role is already attached to a subject.")
        self._wm_subject = subject


def ext(module: str, name: str) -> tuple[type, ...]:
    """The binding's hand-written mixin ``<name>Ext`` from ``wmoop_ext.<module>``, if it defines one.

    A generated class lists the result first among its bases, so the mixin's methods override the
    generated chain and are inherited by subclasses. An import error inside an existing extension
    module is raised, not hidden.
    """
    target = f"wmoop_ext.{module}"
    try:
        mod = importlib.import_module(target)
    except ModuleNotFoundError as exc:
        if exc.name in ("wmoop_ext", target):
            return ()
        raise
    mixin = getattr(mod, f"{name}Ext", None)
    return (mixin,) if isinstance(mixin, type) else ()
