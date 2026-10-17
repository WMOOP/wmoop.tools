# Contributing

This repository is the **WMOOP toolchain** — the WML compiler and the per-language code generators.
WMOOP is a multi-repository project, so the **canonical** contribution process, governance, ethics
and code of conduct live in the documentation repository,
[`wmoop.doc`](https://github.com/WMOOP/wmoop.doc):

- [Contributing guide](https://github.com/WMOOP/wmoop.doc/blob/main/CONTRIBUTING.md)
- [AI contributor protocol](https://github.com/WMOOP/wmoop.doc/blob/main/AI_CONTRIBUTING.md)
- [Governance](https://github.com/WMOOP/wmoop.doc/blob/main/GOVERNANCE.md)
- [Ethics & quality](https://github.com/WMOOP/wmoop.doc/blob/main/ETHICS.md)
- [Design patterns & OOP practices](https://github.com/WMOOP/wmoop.doc/blob/main/PATTERNS.md)

> The canonical documents currently live on the `docs/foundation-v0` branch of `wmoop.doc` and move
> to `main` once that pull request is merged.

## Working in this repository

- **Run:** see the [README](README.md) (`pip install -r requirements.txt`, then
  `python -m wmoop_tools ...` and `python tests/test_conformance.py`).
- **Where changes belong:** this tool *consumes* the canonical WML model from
  [`wmoop.doc/model`](https://github.com/WMOOP/wmoop.doc/tree/main/model). **Model** changes go in
  `wmoop.doc`; **generator** changes (new targets, validation rules) go here. A new target must come
  with a conformance check.
- **Licensing:** by contributing you agree your contributions are released under this repository's
  [LICENSE](LICENSE) (Apache-2.0).

## Local quality gate

Every rule enforced in CI can be run locally. Set up the dev toolchain once:

```bash
python -m pip install -e ".[dev]"
pre-commit install --install-hooks          # runs ruff/mypy/hygiene on every commit
pre-commit install --hook-type commit-msg   # enforces Conventional Commits locally
```

Then, before opening a PR, run the full gate with one command:

```bash
nox                      # lint + type_check + tests + generated
```

…or run the pieces directly:

| Check | Command | What it enforces |
| --- | --- | --- |
| Lint & format | `ruff check .` / `ruff format --check .` | style, imports, bug-prone patterns |
| Types | `mypy` | static type correctness |
| Tests | `pytest` | loader, validator invariants, generators |
| Generators | `python tools/check_generated.py` | **deterministic** output + importable/valid code |
| Model only | `python -m wmoop_tools --model <dir> --check` | the structural invariants, no code emitted |
| Security | `nox -s security` | dependency CVEs (`pip-audit`) + `bandit` |

Unit tests use the self-contained fixture model in `tests/fixtures/model`, so they need no
external repo. The end-to-end `tests/test_conformance.py` additionally needs the canonical model
from `wmoop.doc`; it **skips** automatically when that is absent, or point it at one with
`WMOOP_MODEL=/path/to/wmoop.doc/model`.

## Commit messages

Commits and PR titles must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(optional scope): <description>
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`,
`revert`. This is checked by the `commit-msg` hook and by the **Commit lint** CI workflow. New
generator targets or validation rules should use a scope, e.g. `feat(java): …` or
`feat(validate): …`.

## What CI runs

- **CI** (`.github/workflows/ci.yml`): lint, format, mypy, tests on Python 3.10–3.13 with coverage,
  generator determinism, a build, and a best-effort conformance run against `wmoop.doc`.
- **Security** (`.github/workflows/security.yml`): `pip-audit` + `bandit`, also weekly.
- **Commit lint** (`.github/workflows/commit-lint.yml`): Conventional Commits on the PR title and commits.
