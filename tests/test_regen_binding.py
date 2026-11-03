"""Integration test: ``tools/regen_binding.py`` regenerates a binding and its drift gate holds.

Needs the pinned model (``external/wmoop.doc``, ``git submodule update --init``) and the model
validator's dependencies (``pip install -r external/wmoop.doc/schema/requirements.txt``); it
skips when the model is not checked out.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "external" / "wmoop.doc"
SCRIPT = ROOT / "tools" / "regen_binding.py"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (DOC / "model").is_dir(), reason="external/wmoop.doc is not checked out"),
]


def _run(lang: str, out: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--doc", str(DOC), "--lang", lang, "--out", str(out), *extra],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("lang", ["python", "csharp", "typescript"])
def test_regenerate_then_check(tmp_path, lang):
    out = tmp_path / "generated"
    first = _run(lang, out)
    assert first.returncode == 0, first.stdout + first.stderr
    source = json.loads((out / "WMOOP_SOURCE.json").read_text(encoding="utf-8"))
    assert source["lang"] == lang
    assert len(source["wmoop.doc"]) == 40 and len(source["wmoop.tools"]) == 40

    fresh = _run(lang, out, "--check")
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr


def test_check_reports_stray_and_edited_files(tmp_path):
    out = tmp_path / "generated"
    assert _run("python", out).returncode == 0
    (out / "stray.py").write_text("x = 1\n", encoding="utf-8")
    edited = out / "wmoop" / "transport.py"
    edited.write_text(edited.read_text(encoding="utf-8") + "# hand edit\n", encoding="utf-8")

    stale = _run("python", out, "--check")
    assert stale.returncode == 1
    assert "no longer generated: stray.py" in stale.stdout
    assert "differs: wmoop/transport.py" in stale.stdout


def test_refuses_to_empty_a_directory_it_did_not_generate(tmp_path):
    out = tmp_path / "src"
    out.mkdir()
    (out / "hand_written.py").write_text("x = 1\n", encoding="utf-8")

    refused = _run("python", out)
    assert refused.returncode != 0
    assert "refusing to empty" in refused.stdout + refused.stderr
    assert (out / "hand_written.py").is_file()
