"""In-memory representation of a compiled WML World Model."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Property:
    id: str
    name: str
    type: Optional[str] = None
    unit: Optional[str] = None
    cardinality: str = "0..1"
    required: bool = False
    definition: Optional[str] = None
    default: object = None


@dataclass
class EnumValue:
    id: str
    definition: Optional[str] = None


@dataclass
class Enumeration:
    id: str
    name: str
    values: list = field(default_factory=list)   # list[EnumValue]
    definition: Optional[str] = None


@dataclass
class Concept:
    id: str
    name: str
    kind: str = "concrete"                        # "abstract" | "concrete"
    extends: Optional[str] = None
    implements: list = field(default_factory=list)
    properties: list = field(default_factory=list)  # list[Property]
    definition: Optional[str] = None
    module: Optional[str] = None


@dataclass
class Role:
    id: str
    name: str
    played_by: Optional[str] = None
    context: Optional[str] = None
    properties: list = field(default_factory=list)  # list[Property]
    definition: Optional[str] = None
    module: Optional[str] = None


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
    modules: dict = field(default_factory=dict)       # id -> Module
    concepts: dict = field(default_factory=dict)      # id -> Concept
    roles: dict = field(default_factory=dict)         # id -> Role
    enumerations: dict = field(default_factory=dict)  # id -> Enumeration
    role_bearing: set = field(default_factory=set)    # concept ids that can play roles
