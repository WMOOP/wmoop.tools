"""In-memory representation of a compiled WML World Model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Property:
    id: str
    name: str
    type: str | None = None
    unit: str | None = None
    cardinality: str = "0..1"
    required: bool = False
    definition: str | None = None
    default: object = None


@dataclass
class EnumValue:
    id: str
    definition: str | None = None


@dataclass
class Enumeration:
    id: str
    name: str
    values: list = field(default_factory=list)  # list[EnumValue]
    definition: str | None = None


@dataclass
class Concept:
    id: str
    name: str
    kind: str = "concrete"  # "abstract" | "concrete"
    extends: str | None = None
    implements: list = field(default_factory=list)
    properties: list = field(default_factory=list)  # list[Property]
    definition: str | None = None
    module: str | None = None


@dataclass
class Role:
    id: str
    name: str
    played_by: str | None = None
    context: str | None = None
    properties: list = field(default_factory=list)  # list[Property]
    definition: str | None = None
    module: str | None = None


@dataclass
class Module:
    id: str
    version: str = "0.0.0"
    title: str = ""
    depends_on: list = field(default_factory=list)  # list[str] (module ids)
    concepts: list = field(default_factory=list)
    roles: list = field(default_factory=list)
    enumerations: list = field(default_factory=list)
    dir_name: str = ""


@dataclass
class WorldModel:
    modules: dict = field(default_factory=dict)  # id -> Module
    concepts: dict = field(default_factory=dict)  # id -> Concept
    roles: dict = field(default_factory=dict)  # id -> Role
    enumerations: dict = field(default_factory=dict)  # id -> Enumeration
    role_bearing: set = field(default_factory=set)  # concept ids that can play roles
