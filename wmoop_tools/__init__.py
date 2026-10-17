"""wmoop.tools — the WMOOP toolchain.

Parses the canonical WML World Model (the ``model/`` directory in ``wmoop.doc``),
validates it, and generates idiomatic language bindings from it. This is what makes
the per-language repos (``wmoop.net``, ``wmoop.py``, …) *generated* artifacts rather
than hand-maintained copies — the mechanical core of "write the model once, replicate
everywhere".
"""

__version__ = "0.1.0"
