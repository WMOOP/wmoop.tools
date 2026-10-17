"""Task runner for the WMOOP toolchain quality gate.

Cross-platform (Windows/macOS/Linux): ``pip install nox`` then, for example::

    nox                 # the default gate: lint, type_check, tests, generated
    nox -s lint         # ruff check + ruff format --check
    nox -s format       # auto-fix: ruff --fix + ruff format
    nox -s type_check   # mypy
    nox -s tests        # pytest across supported Pythons
    nox -s generated    # generator determinism & validity
    nox -s security     # pip-audit + bandit
"""

from __future__ import annotations

import nox

nox.options.sessions = ["lint", "type_check", "tests", "generated"]
nox.options.reuse_existing_virtualenvs = True

PYTHONS = ["3.10", "3.11", "3.12", "3.13"]
RUFF = "ruff>=0.6.9"


@nox.session
def lint(session: nox.Session) -> None:
    """Static lint + formatting check (no changes)."""
    session.install(RUFF)
    session.run("ruff", "check", ".")
    session.run("ruff", "format", "--check", ".")


@nox.session
def format(session: nox.Session) -> None:
    """Auto-fix lint issues and reformat."""
    session.install(RUFF)
    session.run("ruff", "check", "--fix", ".")
    session.run("ruff", "format", ".")


@nox.session
def type_check(session: nox.Session) -> None:
    """Static type checking."""
    session.install("-e", ".[dev]")
    session.run("mypy")


@nox.session(python=PYTHONS)
def tests(session: nox.Session) -> None:
    """Unit tests with coverage."""
    session.install("-e", ".[dev]")
    session.run("pytest", "--cov=wmoop_tools", "--cov-report=term-missing")


@nox.session
def generated(session: nox.Session) -> None:
    """Generators must be deterministic and emit valid code."""
    session.install("-e", ".")
    session.run("python", "tools/check_generated.py")


@nox.session
def security(session: nox.Session) -> None:
    """Dependency CVE audit and static security analysis."""
    session.install("-e", ".[dev]")
    session.run("pip-audit")
    session.run("bandit", "-r", "wmoop_tools", "tools", "-c", "pyproject.toml", "--severity-level", "medium")
