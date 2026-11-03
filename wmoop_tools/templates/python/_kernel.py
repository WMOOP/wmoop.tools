"""The runtime kernel every generated WMOOP module imports: errors, identity, quantities, roles, extensions.

``wmoop.core`` re-exports the public names, so a consumer writes ``from wmoop.core import Quantity``.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, TypeVar


class WmoopError(Exception):
    """An error the model defines. ``code`` is its entry in the error-code registry
    (``wmoop.doc/conformance/error-codes.yaml``), the same in every binding, so callers and the
    conformance vectors tell errors apart by code rather than by message or exception type.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WmoopValueError(WmoopError, ValueError):
    """A value the model does not allow; still a ``ValueError``."""


class WmoopTypeError(WmoopError, TypeError):
    """A type the model does not allow; still a ``TypeError``."""


class WmoopStateError(WmoopError, RuntimeError):
    """An operation the object's current state does not allow; still a ``RuntimeError``."""


@dataclass(frozen=True)
class ConceptId:
    """A stable WMOOP identifier, e.g. ``wmoop.transport/Moped`` or an individual's own id."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise WmoopValueError("WM-ID-INVALID", "A ConceptId must be a non-empty identifier.")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Quantity:
    """A value with its unit; a measurable property is never a bare number."""

    value: float
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise WmoopValueError("WM-UNIT-MISSING", "A Quantity must carry a unit.")

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
            raise WmoopTypeError(
                "WM-ABSTRACT-INSTANTIATION", f"{type(self).__name__} is abstract and cannot be instantiated directly."
            )
        self._wm_id = id if isinstance(id, ConceptId) else ConceptId(id)
        if not isinstance(name, str) or not name.strip():
            raise WmoopValueError("WM-REQUIRED-MISSING", "An entity needs a non-empty name.")
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
            raise WmoopTypeError(
                "WM-ROLE-PLAYER-MISMATCH",
                f"{type(role).__name__} is played by {played_by}, which {type(self).__name__} is not.",
            )
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
            raise WmoopStateError("WM-ROLE-ALREADY-ATTACHED", "Role is already attached to a subject.")
        self._wm_subject = subject


class _End:
    """One end of a relation, declared on the class that holds it.

    ``target`` is a class name in the same module, or ``wmoop.<domain>.<Name>``. ``inverse`` names the
    end on the target class when the relation is navigable both ways.
    """

    name = ""

    def __init__(self, target: str, inverse: str | None = None, doc: str = "") -> None:
        self._target, self.inverse, self.__doc__ = target, inverse, doc

    def __set_name__(self, owner: type, name: str) -> None:
        self.name, self._module = name, owner.__module__

    def target(self) -> type:
        module, _, cls = self._target.rpartition(".")
        return getattr(sys.modules[module or self._module], cls)

    def check(self, item: object) -> None:
        if not isinstance(item, self.target()):
            raise WmoopTypeError(
                "WM-RELATION-TARGET-TYPE",
                f"{self.name} relates to {self.target().__name__}, not to {type(item).__name__}.",
            )

    def back(self, item: object) -> _End | None:
        """The opposite end, as declared on ``item``'s class."""
        return getattr(type(item), self.inverse) if self.inverse else None

    def keep(self, obj: object, item: object) -> None:
        """Record ``item`` on ``obj``'s end without touching the opposite end."""
        raise NotImplementedError

    def drop(self, obj: object, item: object) -> None:
        """Forget ``item`` on ``obj``'s end without touching the opposite end."""
        raise NotImplementedError

    @staticmethod
    def links(obj: object) -> dict[str, Any]:
        return obj.__dict__.setdefault("_wm_links", {})


class One(_End):
    """A to-one relation end: an attribute whose assignment also updates the opposite end."""

    def __get__(self, obj: object | None, objtype: type | None = None) -> Any:
        return self if obj is None else self.links(obj).get(self.name)

    def __set__(self, obj: object, value: object | None) -> None:
        if value is not None:
            self.check(value)
        old = self.links(obj).get(self.name)
        if old is value:
            return
        if old is not None and (back := self.back(old)) is not None:
            back.drop(old, obj)
        self.links(obj)[self.name] = value
        if value is not None and (back := self.back(value)) is not None:
            back.keep(value, obj)

    def keep(self, obj: object, item: object) -> None:
        self.links(obj)[self.name] = item

    def drop(self, obj: object, item: object) -> None:
        if self.links(obj).get(self.name) is item:
            self.links(obj)[self.name] = None


class Many(_End):
    """A to-many relation end, read through a :class:`LinkSet`."""

    def __get__(self, obj: object | None, objtype: type | None = None) -> Any:
        return self if obj is None else LinkSet(obj, self)

    def __set__(self, obj: object, value: object) -> None:
        raise AttributeError(f"{self.name} is a to-many relation: use .add() and .remove().")

    def items(self, obj: object) -> list[Any]:
        return self.links(obj).setdefault(self.name, [])

    def keep(self, obj: object, item: object) -> None:
        if not any(i is item for i in self.items(obj)):
            self.items(obj).append(item)

    def drop(self, obj: object, item: object) -> None:
        self.items(obj)[:] = [i for i in self.items(obj) if i is not item]

    def link(self, obj: object, item: object) -> None:
        self.check(item)
        back = self.back(item)
        if isinstance(back, One):
            setattr(item, back.name, obj)  # the to-one end updates both sides
            return
        self.keep(obj, item)
        if back is not None:
            back.keep(item, obj)

    def unlink(self, obj: object, item: object) -> None:
        back = self.back(item)
        if isinstance(back, One):
            if getattr(item, back.name) is obj:
                setattr(item, back.name, None)
            return
        self.drop(obj, item)
        if back is not None:
            back.drop(item, obj)


class LinkSet:
    """The live view of a to-many relation end; ``add`` / ``remove`` keep the opposite end in step."""

    def __init__(self, obj: object, end: Many) -> None:
        self._obj, self._end = obj, end

    def add(self, item: object) -> None:
        if item not in self:
            self._end.link(self._obj, item)

    def remove(self, item: object) -> None:
        if item in self:
            self._end.unlink(self._obj, item)

    def __iter__(self) -> Iterator[Any]:
        return iter(tuple(self._end.items(self._obj)))

    def __len__(self) -> int:
        return len(self._end.items(self._obj))

    def __contains__(self, item: object) -> bool:
        return any(i is item for i in self._end.items(self._obj))

    def __repr__(self) -> str:
        return f"LinkSet({list(self)!r})"


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
