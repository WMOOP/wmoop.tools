#!/usr/bin/env python3
"""Validate commit messages (and PR titles) against Conventional Commits.

Used in three places:

* ``commit-msg`` git hook  — ``check_commit_messages.py <path-to-COMMIT_EDITMSG>``
* CI (pull-request range)   — ``check_commit_messages.py --range origin/main..HEAD``
* CI (PR title)             — ``check_commit_messages.py --text "feat: add X"``

Format enforced (https://www.conventionalcommits.org):

    <type>[optional (scope)][optional !]: <description>

Allowed types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert.

Merge commits, reverts and autosquash (``fixup!`` / ``squash!``) subjects are accepted
as-is so the hook never blocks a legitimate rebase or merge.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TYPES = ("feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert")

# type(scope)!: subject   — scope and the breaking-change "!" are optional.
PATTERN = re.compile(r"^(?:" + "|".join(TYPES) + r")(?:\([a-z0-9][\w.\-/ ]*\))?!?: .+")

# Subjects we never want to reject (git/tooling generated).
EXEMPT = re.compile(r"^(Merge |Revert |fixup! |squash! |amend! )")

MAX_SUBJECT_LEN = 100


def _problem(subject: str) -> str | None:
    """Return an error string if ``subject`` is invalid, else ``None``."""
    if not subject.strip():
        return "empty commit subject"
    if EXEMPT.match(subject):
        return None
    if not PATTERN.match(subject):
        return (
            "not a Conventional Commit. Expected '<type>(optional scope): <description>', "
            f"where <type> is one of: {', '.join(TYPES)}"
        )
    if len(subject) > MAX_SUBJECT_LEN:
        return f"subject longer than {MAX_SUBJECT_LEN} characters ({len(subject)})"
    return None


def _subject_from_file(path: str) -> str:
    """First non-empty, non-comment line of a commit message file."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _subjects_from_range(rev_range: str) -> list[str]:
    out = subprocess.run(
        ["git", "log", "--no-merges", "--format=%s", rev_range],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def _check(subjects: list[tuple[str, str]]) -> int:
    """``subjects`` is a list of (origin, subject). Returns process exit code."""
    failures = 0
    for origin, subject in subjects:
        err = _problem(subject)
        if err:
            failures += 1
            print(f"FAIL [{origin}] {subject!r}\n     {err}", file=sys.stderr)
        else:
            print(f"ok   [{origin}] {subject}")
    if failures:
        print(f"\n{failures} commit message(s) failed the Conventional Commits check.", file=sys.stderr)
        print("See https://www.conventionalcommits.org/ or CONTRIBUTING.md.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate commit messages against Conventional Commits.")
    ap.add_argument("files", nargs="*", help="commit-message file(s) (commit-msg hook mode)")
    ap.add_argument("--range", dest="rev_range", help="validate every subject in a git range, e.g. origin/main..HEAD")
    ap.add_argument("--text", action="append", default=[], help="validate a literal subject (e.g. a PR title)")
    args = ap.parse_args(argv)

    subjects: list[tuple[str, str]] = []
    subjects += [("text", t) for t in args.text]
    if args.rev_range:
        try:
            subjects += [("commit", s) for s in _subjects_from_range(args.rev_range)]
        except subprocess.CalledProcessError as exc:
            print(f"git failed for range {args.rev_range!r}: {exc.stderr}", file=sys.stderr)
            return 2
    subjects += [(f, _subject_from_file(f)) for f in args.files]

    if not subjects:
        ap.error("nothing to check: pass a commit-message file, --range, or --text")
    return _check(subjects)


if __name__ == "__main__":
    sys.exit(main())
