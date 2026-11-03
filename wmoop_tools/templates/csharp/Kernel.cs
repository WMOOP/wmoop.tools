#nullable enable
using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.Reflection;

namespace Wmoop.Core;

/// <summary>
/// An error the model defines. <see cref="Code"/> is its entry in the error-code registry
/// (<c>wmoop.doc/conformance/error-codes.yaml</c>), the same in every binding, so callers and the
/// conformance vectors tell errors apart by code rather than by message or exception type.
/// </summary>
public interface IWmoopError
{
    string Code { get; }
}

/// <summary>A value the model does not allow; still an <see cref="ArgumentException"/>.</summary>
public sealed class WmoopArgumentException : ArgumentException, IWmoopError
{
    public WmoopArgumentException(string code, string message, string? paramName = null)
        : base(message, paramName) => Code = code;

    public string Code { get; }
}

/// <summary>An operation the object's current state does not allow; still an <see cref="InvalidOperationException"/>.</summary>
public sealed class WmoopInvalidOperationException : InvalidOperationException, IWmoopError
{
    public WmoopInvalidOperationException(string code, string message)
        : base(message) => Code = code;

    public string Code { get; }
}

/// <summary>A stable WMOOP identifier, e.g. <c>wmoop.transport/Moped</c> or an individual's own id.</summary>
public readonly struct ConceptId : IEquatable<ConceptId>
{
    public ConceptId(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new WmoopArgumentException("WM-ID-INVALID", "A ConceptId must be a non-empty identifier.", nameof(value));
        Value = value;
    }

    public string Value { get; }

    public static implicit operator ConceptId(string value) => new(value);
    public bool Equals(ConceptId other) => string.Equals(Value, other.Value, StringComparison.Ordinal);
    public override bool Equals(object? obj) => obj is ConceptId other && Equals(other);
    public override int GetHashCode() => StringComparer.Ordinal.GetHashCode(Value ?? string.Empty);
    public override string ToString() => Value ?? string.Empty;
    public static bool operator ==(ConceptId a, ConceptId b) => a.Equals(b);
    public static bool operator !=(ConceptId a, ConceptId b) => !a.Equals(b);
}

/// <summary>A value with its unit; a measurable property is never a bare number.</summary>
public readonly struct Quantity : IEquatable<Quantity>
{
    public Quantity(double value, string unit)
    {
        if (string.IsNullOrWhiteSpace(unit))
            throw new WmoopArgumentException("WM-UNIT-MISSING", "A Quantity must carry a unit.", nameof(unit));
        Value = value;
        Unit = unit;
    }

    public double Value { get; }
    public string Unit { get; }

    public bool Equals(Quantity other) => Value.Equals(other.Value) && string.Equals(Unit, other.Unit, StringComparison.Ordinal);
    public override bool Equals(object? obj) => obj is Quantity other && Equals(other);
    public override int GetHashCode() => HashCode.Combine(Value, Unit);
    public override string ToString() => Value.ToString(CultureInfo.InvariantCulture) + " " + Unit;
    public static bool operator ==(Quantity a, Quantity b) => a.Equals(b);
    public static bool operator !=(Quantity a, Quantity b) => !a.Equals(b);

    /// <summary>
    /// This quantity's magnitude in <paramref name="unit"/>, a unit of the same kind:
    /// <c>new Quantity(45, "km/h").In("m/s")</c> is 12.5.
    /// </summary>
    public double In(string unit) => Units.Convert(this, unit);
}

/// <summary>
/// The unit catalogue: every <c>wmoop.core/Unit</c> individual of the model, by symbol, with the
/// quantity kind it measures and its conversion to that kind's canonical unit (a value in the unit is
/// <c>Factor * value + Offset</c> canonical units), and every <c>wmoop.core/QuantityKind</c> with its SI
/// dimension. Generated quantity properties check against it.
/// </summary>
public static partial class Units
{
    private const string DimensionMismatch = "WM-UNIT-DIMENSION-MISMATCH";

    private static readonly Dictionary<string, (string Kind, double Factor, double Offset)> BySymbol = Load();
    private static readonly Dictionary<string, string> DimensionOf = LoadDimensions();

    /// <summary>The quantity kind <paramref name="symbol"/> measures, e.g. <c>wmoop.core/Speed</c> for <c>km/h</c>; null if it is not in the catalogue.</summary>
    public static string? KindOf(string symbol) =>
        symbol is not null && BySymbol.TryGetValue(symbol, out var unit) ? unit.Kind : null;

    /// <summary>
    /// Throws unless a property declared in <paramref name="unit"/>, of quantity kind <paramref name="kind"/>,
    /// may hold <paramref name="value"/>: any catalogue unit of that kind may (<c>m/s</c> for a speed in
    /// <c>km/h</c>). <paramref name="kind"/> is empty when the model does not say, and then only <paramref name="unit"/> may.
    /// </summary>
    public static void Require(Quantity value, string unit, string kind, string member)
    {
        if (value.Unit == unit)
            return;
        if (value.Unit is null)
            throw new WmoopArgumentException("WM-UNIT-MISSING", $"{member} must be in {unit}; default(Quantity) carries no unit.", member);
        if (kind.Length == 0)
            throw new WmoopArgumentException(DimensionMismatch, $"{member} must be in {unit}, not in {value.Unit}.", member);
        var name = Local(kind);
        var measures = KindOf(value.Unit);
        if (measures is null)
            throw new WmoopArgumentException(DimensionMismatch,
                $"{member} must be in {unit} or another {name} unit; {value.Unit} is not in the unit catalogue.", member);
        if (measures != kind)
            throw new WmoopArgumentException(Mismatch(measures, kind),
                $"{member} must be in {unit} or another {name} unit; {value.Unit} measures {Local(measures)}.", member);
    }

    /// <summary>As <see cref="Require(Quantity, string, string, string)"/>; an absent value passes.</summary>
    public static void Require(Quantity? value, string unit, string kind, string member)
    {
        if (value is { } q)
            Require(q, unit, kind, member);
    }

    /// <summary>As <see cref="Require(Quantity, string, string, string)"/>, for each value.</summary>
    public static void Require(IEnumerable<Quantity>? values, string unit, string kind, string member)
    {
        foreach (var q in values ?? Array.Empty<Quantity>())
            Require(q, unit, kind, member);
    }

    internal static double Convert(Quantity quantity, string unit)
    {
        if (quantity.Unit == unit)
            return quantity.Value;
        if (quantity.Unit is null || !BySymbol.TryGetValue(quantity.Unit, out var here) || !BySymbol.TryGetValue(unit, out var there))
            throw new WmoopArgumentException(DimensionMismatch, $"Cannot express {quantity} in {unit}: the unit catalogue does not have both units.", nameof(unit));
        if (here.Kind != there.Kind)
            throw new WmoopArgumentException(Mismatch(here.Kind, there.Kind),
                $"Cannot express {quantity} in {unit}: {Local(here.Kind)} is not {Local(there.Kind)}.", nameof(unit));
        return (quantity.Value * here.Factor + here.Offset - there.Offset) / there.Factor;
    }

    /// <summary>
    /// The code for a quantity of <paramref name="kind"/> met where <paramref name="expected"/> is: a different
    /// SI dimension, or the same dimension but another kind (Angle and Count are both dimensionless).
    /// </summary>
    private static string Mismatch(string kind, string expected) =>
        DimensionOf.TryGetValue(kind, out var a) && DimensionOf.TryGetValue(expected, out var b) && a == b
            ? "WM-QUANTITYKIND-MISMATCH"
            : DimensionMismatch;

    private static string Local(string qname) => qname[(qname.LastIndexOf('/') + 1)..];

    private static Dictionary<string, (string Kind, double Factor, double Offset)> Load()
    {
        var units = new Dictionary<string, (string Kind, double Factor, double Offset)>(StringComparer.Ordinal);
        foreach (var (symbol, kind, factor, offset) in Catalog())
            units[symbol] = (kind, factor, offset);
        return units;
    }

    private static Dictionary<string, string> LoadDimensions()
    {
        var kinds = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (kind, dimension) in Dimensions())
            kinds[kind] = dimension;
        return kinds;
    }

    // The generated half (Units.Gen.cs): one entry per wmoop.core/Unit individual of the model, and the
    // SI dimension (L M T I Θ N J exponents) of every wmoop.core/QuantityKind individual that records one.
    private static partial (string Symbol, string Kind, double Factor, double Offset)[] Catalog();

    private static partial (string Kind, string Dimension)[] Dimensions();
}

/// <summary>The role API every entity offers.</summary>
public interface IHasRoles
{
    IReadOnlyCollection<IRole> Roles { get; }
    T AddRole<T>(T role) where T : Role;
    bool HasRole<T>() where T : class, IRole;
    T? GetRole<T>() where T : class, IRole;
}

public interface IRole
{
    ConceptId RoleType { get; }
    Entity? Subject { get; }
}

/// <summary>Base of every generated concept: identity, name, and the roles it plays.</summary>
public abstract class Entity : IHasRoles
{
    private readonly List<IRole> _roles = new();
    private readonly string _name = string.Empty;

    public required ConceptId Id { get; init; }

    public required string Name
    {
        get => _name;
        init => _name = string.IsNullOrWhiteSpace(value)
            ? throw new WmoopArgumentException("WM-REQUIRED-MISSING", "An entity needs a non-empty name.", nameof(Name))
            : value;
    }

    public IReadOnlyCollection<IRole> Roles => _roles;

    /// <summary>
    /// Attach a role by composition; its <c>PlayedBy</c> type must be one of this entity's types, and this
    /// entity may not already hold as many roles of its type as <c>MaxPerPlayer</c> allows.
    /// </summary>
    public T AddRole<T>(T role) where T : Role
    {
        ArgumentNullException.ThrowIfNull(role);
        if (role.PlayedBy.Length > 0 && !IsA(role.PlayedBy))
            throw new WmoopInvalidOperationException("WM-ROLE-PLAYER-MISMATCH",
                $"{role.GetType().Name} is played by {role.PlayedBy}, which {GetType().Name} is not.");
        if (role.Subject is not null)
            throw new WmoopInvalidOperationException("WM-ROLE-ALREADY-ATTACHED", "Role is already attached to a subject.");
        if (role.MaxPerPlayer is int max)
        {
            var held = 0;
            foreach (var r in _roles)
                if (r.RoleType == role.RoleType)
                    held++;
            if (held >= max)
                throw new WmoopInvalidOperationException("WM-ROLE-DUPLICATE",
                    $"{GetType().Name} already plays {max} {role.GetType().Name} role(s), the most its cardinality_per_player allows.");
        }
        role.AttachTo(this);
        _roles.Add(role);
        return role;
    }

    public bool HasRole<T>() where T : class, IRole => GetRole<T>() is not null;

    public T? GetRole<T>() where T : class, IRole
    {
        foreach (var r in _roles)
            if (r is T t)
                return t;
        return null;
    }

    /// <summary>True when this entity's type, or one of its ancestors, is the model type <paramref name="qname"/>.</summary>
    public bool IsA(string qname)
    {
        for (var t = GetType(); t is not null; t = t.BaseType)
        {
            var field = t.GetField("WmId", BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly);
            if (field is { IsLiteral: true } && field.GetRawConstantValue() is string id && id == qname)
                return true;
        }
        return false;
    }

    public override string ToString() => $"{Name} [{Id}]";
}

/// <summary>
/// A to-many relation end. <see cref="Add"/> and <see cref="Remove"/> keep the opposite end in step;
/// the generated code supplies how.
/// </summary>
public sealed class Links<T> : IReadOnlyCollection<T> where T : class
{
    private readonly List<T> _items = new();
    private readonly Action<T> _link;
    private readonly Action<T> _unlink;

    public Links(Action<T> link, Action<T> unlink)
    {
        _link = link ?? throw new ArgumentNullException(nameof(link));
        _unlink = unlink ?? throw new ArgumentNullException(nameof(unlink));
    }

    public int Count => _items.Count;

    public bool Contains(T item) => _items.Exists(i => ReferenceEquals(i, item));

    public void Add(T item)
    {
        ArgumentNullException.ThrowIfNull(item);
        if (!Contains(item))
            _link(item);
    }

    public void Remove(T item)
    {
        ArgumentNullException.ThrowIfNull(item);
        if (Contains(item))
            _unlink(item);
    }

    public IEnumerator<T> GetEnumerator() => _items.GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();

    /// <summary>Adds without touching the opposite end. For generated wiring code only.</summary>
    [EditorBrowsable(EditorBrowsableState.Never)]
    public void Keep(T item)
    {
        if (!Contains(item))
            _items.Add(item);
    }

    /// <summary>Removes without touching the opposite end. For generated wiring code only.</summary>
    [EditorBrowsable(EditorBrowsableState.Never)]
    public void Drop(T item) => _items.RemoveAll(i => ReferenceEquals(i, item));
}

/// <summary>Base of every generated role: a facet an entity plays, attached by composition.</summary>
public abstract class Role : IRole
{
    public abstract ConceptId RoleType { get; }

    /// <summary>The model type that may play this role (empty: any entity).</summary>
    public virtual string PlayedBy => string.Empty;

    /// <summary>How many roles of this type one entity may hold at once (<c>cardinality_per_player</c>); null: any number.</summary>
    public virtual int? MaxPerPlayer => null;

    public Entity? Subject { get; private set; }

    internal void AttachTo(Entity subject)
    {
        if (Subject is not null)
            throw new WmoopInvalidOperationException("WM-ROLE-ALREADY-ATTACHED", "Role is already attached to a subject.");
        Subject = subject ?? throw new ArgumentNullException(nameof(subject));
    }
}
