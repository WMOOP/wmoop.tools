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
