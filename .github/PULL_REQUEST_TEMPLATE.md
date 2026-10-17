<!--
Thank you for contributing to the WMOOP toolchain.
Keep the PR title in Conventional Commits form, e.g. "feat(csharp): emit records".
-->

## What & why

<!-- What does this change do, and why is it needed? -->

## Type of change

- [ ] Bug fix
- [ ] New feature (e.g. a new generator target or validation rule)
- [ ] Refactor / internal change
- [ ] Documentation
- [ ] CI / tooling

## Checklist

- [ ] The PR title follows [Conventional Commits](https://www.conventionalcommits.org/).
- [ ] `ruff check .` and `ruff format --check .` pass (or `nox -s lint`).
- [ ] `mypy` passes (or `nox -s type_check`).
- [ ] `pytest` passes (or `nox -s tests`).
- [ ] `python tools/check_generated.py` passes (generators stay deterministic & valid).
- [ ] A **new generator target** comes with a conformance check (see CONTRIBUTING.md).
- [ ] Generated code was **not** hand-edited (behaviour belongs in hand-written extensions — the generation gap).
- [ ] Docs updated if behaviour or usage changed.

## Notes for reviewers

<!-- Anything reviewers should pay special attention to. Model changes belong in wmoop.doc, not here. -->
