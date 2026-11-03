/**
 * The runtime kernel every generated WMOOP module imports: errors, identity, quantities and units,
 * entities and roles, relation ends, and the hook for hand-written behaviour.
 *
 * `wmoop/core` re-exports these names, so a consumer writes `import { Quantity } from "./wmoop/core.js"`.
 * The kernel uses only the language: no Node.js, no DOM, no dependency.
 *
 * @module
 */

/**
 * An error the model defines. `code` is its entry in the error-code registry
 * (`wmoop.doc/conformance/error-codes.yaml`), the same in every binding, so callers and the
 * conformance vectors tell errors apart by code rather than by message or class.
 */
export class WmoopError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "WmoopError";
    this.code = code;
  }
}

/** A class of the model, abstract or not, as `instanceof` and {@link Entity.getRole} take it. */
export type Type<T> = abstract new (...args: never[]) => T;

/** A stable WMOOP identifier, e.g. `wmoop.transport/Moped` or an individual's own id. */
export class ConceptId {
  readonly value: string;

  constructor(value: string) {
    if (typeof value !== "string" || value.trim() === "") {
      throw new WmoopError("WM-ID-INVALID", "A ConceptId must be a non-empty identifier.");
    }
    this.value = value;
    Object.freeze(this);
  }

  /** Value equality: two ids are equal when their text is. */
  equals(other: unknown): boolean {
    return other instanceof ConceptId && other.value === this.value;
  }

  toString(): string {
    return this.value;
  }
}

const DIMENSION_MISMATCH = "WM-UNIT-DIMENSION-MISMATCH";

/**
 * The unit catalogue, by symbol: the quantity kind, factor and offset, where a value in the unit is
 * `factor * value + offset` in the kind's canonical unit. The generator fills it from the model's
 * `wmoop.core/Unit` individuals (docs/02-meta-model.md §6.4) at the end of this file; it stays empty
 * without them.
 */
const UNITS = new Map<string, readonly [kind: string, factor: number, offset: number]>();

/**
 * The SI dimension (L M T I Θ N J exponents) of each quantity kind that records one, from the model's
 * `wmoop.core/QuantityKind` individuals.
 */
const KINDS = new Map<string, string>();

function local(qname: string): string {
  return qname.slice(qname.lastIndexOf("/") + 1);
}

/**
 * The code for a quantity of `kind` met where `expected` is: a different SI dimension, or the same
 * dimension but another kind (Angle and Count are both dimensionless).
 */
function mismatch(kind: string, expected: string): string {
  const here = KINDS.get(kind);
  return here !== undefined && here === KINDS.get(expected) ? "WM-QUANTITYKIND-MISMATCH" : DIMENSION_MISMATCH;
}

/** What `value` is, for an error message: its class, or its JavaScript type. */
function kindOf(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return value === null ? "null" : typeof value;
  }
  const type: unknown = Object.getPrototypeOf(value)?.constructor;
  return typeof type === "function" && type.name !== "" ? type.name : "object";
}

/** A value with its unit; a measurable property is never a bare number. */
export class Quantity {
  readonly value: number;
  readonly unit: string;

  constructor(value: number, unit: string) {
    if (typeof unit !== "string" || unit.trim() === "") {
      throw new WmoopError("WM-UNIT-MISSING", "A Quantity must carry a unit.");
    }
    if (typeof value !== "number") {
      throw new WmoopError("WM-TYPE-MISMATCH", `A Quantity's value is a number, not ${kindOf(value)}.`);
    }
    this.value = value;
    this.unit = unit;
    Object.freeze(this);
  }

  /** Value equality: the same magnitude in the same unit. */
  equals(other: unknown): boolean {
    return other instanceof Quantity && other.value === this.value && other.unit === this.unit;
  }

  /** The value in its shortest round-trip form, then the unit: `49 cm3`, `12.5 m/s`, `5.97e+24 kg`. */
  toString(): string {
    return `${this.value} ${this.unit}`;
  }

  /** This quantity's magnitude in `unit`, a unit of the same kind: `new Quantity(45, "km/h").in("m/s")` is 12.5. */
  in(unit: string): number {
    if (unit === this.unit) {
      return this.value;
    }
    const here = UNITS.get(this.unit);
    const there = UNITS.get(unit);
    if (here === undefined || there === undefined) {
      throw new WmoopError(
        DIMENSION_MISMATCH,
        `Cannot express ${this} in ${unit}: the unit catalogue does not have both units.`,
      );
    }
    if (here[0] !== there[0]) {
      throw new WmoopError(
        mismatch(here[0], there[0]),
        `Cannot express ${this} in ${unit}: ${local(here[0])} is not ${local(there[0])}.`,
      );
    }
    return (this.value * here[1] + here[2] - there[2]) / there[1];
  }
}

/** The quantity kind `symbol` measures, e.g. `wmoop.core/Speed` for `km/h`; null if it is not in the catalogue. */
export function unitKind(symbol: string): string | null {
  return UNITS.get(symbol)?.[0] ?? null;
}

/**
 * `value`, when a property declared in `unit`, of quantity kind `kind`, may hold it.
 *
 * Any catalogue unit of that kind is accepted and kept as given (`m/s` for a speed in `km/h`).
 * `kind` is empty when the model does not say, and then only `unit` itself is.
 */
export function checkQuantity(value: unknown, unit: string, kind: string, member: string): Quantity {
  if (!(value instanceof Quantity)) {
    throw new WmoopError("WM-TYPE-MISMATCH", `${member} is a quantity in ${unit}, not ${kindOf(value)} ${String(value)}.`);
  }
  if (value.unit === unit) {
    return value;
  }
  if (kind === "") {
    throw new WmoopError(DIMENSION_MISMATCH, `${member} must be in ${unit}, not in ${value.unit}.`);
  }
  const measures = unitKind(value.unit);
  if (measures === null) {
    throw new WmoopError(
      DIMENSION_MISMATCH,
      `${member} must be in ${unit} or another ${local(kind)} unit; ${value.unit} is not in the unit catalogue.`,
    );
  }
  if (measures !== kind) {
    throw new WmoopError(
      mismatch(measures, kind),
      `${member} must be in ${unit} or another ${local(kind)} unit; ${value.unit} measures ${local(measures)}.`,
    );
  }
  return value;
}

/** What every entity is built with: its identity and its name. */
export interface EntityInit {
  /** The entity's identifier, e.g. `wmoop.nature/person/ada-lovelace`. */
  readonly id: ConceptId | string;
  /** A human-readable, non-empty name. */
  readonly name: string;
}

let attachRole!: (role: Role, subject: Entity) => void;

/**
 * Base of every generated concept: identity, name, and the roles it plays.
 *
 * A class whose own `WM_KIND` is `"abstract"` cannot be instantiated; a hand-written subclass can.
 */
export abstract class Entity {
  /** The model type the class is generated from, e.g. `wmoop.transport/Moped`. */
  static readonly WM_ID: string = "";
  /** `"abstract"` or `"concrete"`, as the model declares the concept. */
  static readonly WM_KIND: string = "abstract";

  readonly #id: ConceptId;
  readonly #name: string;
  readonly #roles: Role[] = [];

  constructor(init: EntityInit) {
    const type = new.target as typeof Entity;
    if (Object.hasOwn(type, "WM_KIND") && type.WM_KIND === "abstract") {
      throw new WmoopError(
        "WM-ABSTRACT-INSTANTIATION",
        `${type.name} is abstract and cannot be instantiated directly.`,
      );
    }
    this.#id = init.id instanceof ConceptId ? init.id : new ConceptId(init.id);
    if (typeof init.name !== "string" || init.name.trim() === "") {
      throw new WmoopError("WM-REQUIRED-MISSING", "An entity needs a non-empty name.");
    }
    this.#name = init.name;
  }

  get id(): ConceptId {
    return this.#id;
  }

  get name(): string {
    return this.#name;
  }

  /** The roles this entity plays, in the order they were attached. */
  get roles(): readonly Role[] {
    return Object.freeze([...this.#roles]);
  }

  /** True when this entity's class, or one of its ancestors, is the model type `qname`. */
  isA(qname: string): boolean {
    for (let type: unknown = this.constructor; typeof type === "function"; type = Object.getPrototypeOf(type)) {
      if (Object.hasOwn(type, "WM_ID") && (type as typeof Entity).WM_ID === qname) {
        return true;
      }
    }
    return false;
  }

  /**
   * Attaches `role` by composition. The role's `WM_PLAYED_BY` type must be one of this entity's types,
   * and this entity may not already hold as many roles of its type as `cardinality_per_player` allows.
   */
  addRole<R extends Role>(role: R): R {
    const type = role.constructor as typeof Role;
    if (type.WM_PLAYED_BY !== "" && !this.isA(type.WM_PLAYED_BY)) {
      throw new WmoopError(
        "WM-ROLE-PLAYER-MISMATCH",
        `${type.name} is played by ${type.WM_PLAYED_BY}, which ${this.constructor.name} is not.`,
      );
    }
    if (role.subject !== null) {
      throw new WmoopError("WM-ROLE-ALREADY-ATTACHED", "Role is already attached to a subject.");
    }
    const limit = type.WM_MAX_PER_PLAYER;
    if (limit !== null && this.#roles.filter((r) => (r.constructor as typeof Role).WM_ID === type.WM_ID).length >= limit) {
      throw new WmoopError(
        "WM-ROLE-DUPLICATE",
        `${this.constructor.name} already plays ${limit} ${type.name} role(s), the most its cardinality_per_player allows.`,
      );
    }
    attachRole(role, this);
    this.#roles.push(role);
    return role;
  }

  hasRole(type: Type<Role>): boolean {
    return this.getRole(type) !== null;
  }

  /** The first role of class `type` this entity plays, or null. */
  getRole<R extends Role>(type: Type<R>): R | null {
    for (const role of this.#roles) {
      if (role instanceof type) {
        return role;
      }
    }
    return null;
  }

  toString(): string {
    return `${this.#name} [${this.#id}]`;
  }
}

/** Base of every generated role: a facet an entity plays, attached by composition. */
export abstract class Role {
  /** The model type the class is generated from, e.g. `wmoop.transport/Driver`. */
  static readonly WM_ID: string = "";
  /** The model type that may play this role (empty: any entity). */
  static readonly WM_PLAYED_BY: string = "";
  /** How many roles of this type one entity may hold at once (`cardinality_per_player`); null: any number. */
  static readonly WM_MAX_PER_PLAYER: number | null = null;

  #subject: Entity | null = null;

  static {
    attachRole = (role, subject) => {
      if (role.#subject !== null) {
        throw new WmoopError("WM-ROLE-ALREADY-ATTACHED", "Role is already attached to a subject.");
      }
      role.#subject = subject;
    };
  }

  get roleType(): ConceptId {
    return new ConceptId((this.constructor as typeof Role).WM_ID);
  }

  /** The entity that plays this role, or null before it is attached. */
  get subject(): Entity | null {
    return this.#subject;
  }
}

/**
 * `value` for the relation end `member`, after checking it is a `type`; an absent value is null.
 * For generated code.
 */
export function relationTarget<T>(value: T | null | undefined, type: Type<T>, member: string): T | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (!(value instanceof type)) {
    throw new WmoopError("WM-RELATION-TARGET-TYPE", `${member} relates to ${type.name}, not to ${kindOf(value)}.`);
  }
  return value;
}

/**
 * A to-many relation end: the live, ordered set of the objects at the other end. `add` and `delete`
 * keep the opposite end in step; the generated code supplies how.
 */
export class Links<T extends object> implements Iterable<T> {
  readonly #items: T[] = [];
  readonly #type: Type<T>;
  readonly #member: string;
  readonly #link: (item: T) => void;
  readonly #unlink: (item: T) => void;

  /** Without `link` and `unlink` the end has no opposite: they only keep and drop. */
  constructor(type: Type<T>, member: string, link?: (item: T) => void, unlink?: (item: T) => void) {
    this.#type = type;
    this.#member = member;
    this.#link = link ?? ((item) => this.keep(item));
    this.#unlink = unlink ?? ((item) => this.drop(item));
  }

  get size(): number {
    return this.#items.length;
  }

  has(item: T): boolean {
    return this.#items.includes(item);
  }

  /** Adds `item`, and the opposite end follows. */
  add(item: T): this {
    relationTarget(item, this.#type, this.#member);
    if (!this.has(item)) {
      this.#link(item);
    }
    return this;
  }

  /** Removes `item`, and the opposite end follows; false when it was not there. */
  delete(item: T): boolean {
    if (!this.has(item)) {
      return false;
    }
    this.#unlink(item);
    return true;
  }

  /** The items, in the order they were added, as a snapshot: removing while iterating is safe. */
  [Symbol.iterator](): Iterator<T> {
    return [...this.#items][Symbol.iterator]();
  }

  /** Adds without touching the opposite end. For generated wiring code only. */
  keep(item: T): void {
    if (!this.has(item)) {
      this.#items.push(item);
    }
  }

  /** Removes without touching the opposite end. For generated wiring code only. */
  drop(item: T): void {
    const at = this.#items.indexOf(item);
    if (at >= 0) {
      this.#items.splice(at, 1);
    }
  }
}

/**
 * Adds hand-written behaviour to a generated class: the generation gap, TypeScript style
 * (docs/03-architecture.md §2.2). Every getter, setter and method of `members` is defined on the
 * class's prototype, so its subclasses inherit it and a subclass's own `extend` overrides it. In
 * `members`, `this` is the instance and `super.x` is the member as the parent class has it.
 *
 * The members' types come from augmenting the generated module, in the same hand-written file:
 *
 * ```ts
 * import { extend } from "../../generated/wmoop/core.js";
 * import { Vehicle } from "../../generated/wmoop/transport.js";
 *
 * declare module "../../generated/wmoop/transport.js" {
 *   interface Vehicle {
 *     describe(): string;
 *   }
 * }
 *
 * extend(Vehicle, {
 *   describe() {
 *     return `${this.name} has ${this.wheelCount} wheels.`;
 *   },
 * });
 * ```
 *
 * A member the class itself already has (generated, or added by an earlier `extend`) is refused.
 */
export function extend<T extends object>(type: Type<T>, members: Partial<T> & ThisType<T>): void {
  const prototype = type.prototype as object;
  Object.setPrototypeOf(members, Object.getPrototypeOf(prototype));
  for (const key of Reflect.ownKeys(members)) {
    if (Object.hasOwn(prototype, key)) {
      throw new TypeError(`${type.name} already has a member ${String(key)}; extend() only adds members.`);
    }
    Object.defineProperty(prototype, key, Object.getOwnPropertyDescriptor(members, key) as PropertyDescriptor);
  }
}

/** `value` for the required slot `member`. For generated code. */
export function required<T>(value: T | null | undefined, member: string): T {
  if (value === null || value === undefined) {
    throw new WmoopError("WM-REQUIRED-MISSING", `${member} is required.`);
  }
  return value;
}

/** `value` for the optional slot `member`, through `check` when it is present; absent is null. For generated code. */
export function optional<T>(value: T | null | undefined, check?: (value: T) => T): T | null {
  if (value === null || value === undefined) {
    return null;
  }
  return check === undefined ? value : check(value);
}

/**
 * The values of the many-valued slot `member`, each through `check`, as a frozen array. `atLeastOne`
 * for a `1..*` slot, which must be given and not be empty. For generated code.
 */
export function many<T>(
  values: Iterable<T> | null | undefined,
  member: string,
  atLeastOne: boolean,
  check?: (value: T) => T,
): readonly T[] {
  if (values === null || values === undefined) {
    if (atLeastOne) {
      throw new WmoopError("WM-REQUIRED-MISSING", `${member} is required.`);
    }
    return Object.freeze([]);
  }
  const items = check === undefined ? [...values] : [...values].map(check);
  if (atLeastOne && items.length === 0) {
    throw new WmoopError("WM-CARDINALITY", `${member} needs at least one value.`);
  }
  return Object.freeze(items);
}

/**
 * An enumeration of the model, frozen: each value by its name, and each value is its model id
 * (`LicenceCategory.AM` is `"AM"`). For generated code.
 */
export function enumeration<const T extends Readonly<Record<string, string>>>(values: T): T {
  return Object.freeze(values);
}

/** `value` for the slot `member`, after checking it is a value of `enumeration`. For generated code. */
export function oneOf<T extends string>(enumeration: Readonly<Record<string, T>>, value: T, member: string): T {
  const values: readonly string[] = Object.values(enumeration);
  if (!values.includes(value)) {
    throw new WmoopError("WM-TYPE-MISMATCH", `${member} is one of ${values.join(", ")}, not ${String(value)}.`);
  }
  return value;
}

/** A model `date`: the calendar day, as a `Date` at midnight UTC. */
export function date(year: number, month: number, day: number): Date {
  return new Date(Date.UTC(year, month - 1, day));
}

/** Sets the model's individual `value` as the read-only static `name` of `type`. For generated code. */
export function individual<T>(type: Type<T>, name: string, value: T): void {
  Object.defineProperty(type, name, { value, enumerable: true });
}
