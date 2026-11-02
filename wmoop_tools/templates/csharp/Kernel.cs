#nullable enable
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;

namespace Wmoop.Core;

/// <summary>A stable WMOOP identifier, e.g. <c>wmoop.transport/Moped</c> or an individual's own id.</summary>
public readonly struct ConceptId : IEquatable<ConceptId>
{
    public ConceptId(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new ArgumentException("A ConceptId must be a non-empty identifier.", nameof(value));
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
            throw new ArgumentException("A Quantity must carry a unit.", nameof(unit));
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

    public required ConceptId Id { get; init; }
    public required string Name { get; init; }

    public IReadOnlyCollection<IRole> Roles => _roles;

    /// <summary>Attach a role by composition; its <c>PlayedBy</c> type must be one of this entity's types.</summary>
    public T AddRole<T>(T role) where T : Role
    {
        ArgumentNullException.ThrowIfNull(role);
        if (role.PlayedBy.Length > 0 && !IsA(role.PlayedBy))
            throw new InvalidOperationException($"{role.GetType().Name} is played by {role.PlayedBy}, which {GetType().Name} is not.");
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

/// <summary>Base of every generated role: a facet an entity plays, attached by composition.</summary>
public abstract class Role : IRole
{
    public abstract ConceptId RoleType { get; }

    /// <summary>The model type that may play this role (empty: any entity).</summary>
    public virtual string PlayedBy => string.Empty;

    public Entity? Subject { get; private set; }

    internal void AttachTo(Entity subject)
    {
        if (Subject is not null)
            throw new InvalidOperationException("Role is already attached to a subject.");
        Subject = subject ?? throw new ArgumentNullException(nameof(subject));
    }
}
