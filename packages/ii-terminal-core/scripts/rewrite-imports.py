#!/usr/bin/env python3
"""Rewrite $wealth/* imports to relative paths within ii-terminal-core.

Mapping rules (source $wealth/* path → package subsystem):
  $wealth/components/screener/terminal/* → components/screener-terminal/*
  $wealth/components/*                   → components/*
  $wealth/stores/*                       → stores/*
  $wealth/state/*                        → state/*
  $wealth/types/*                        → types/*
  $wealth/utils/*                        → utils/*
  $wealth/util/*                         → utils/*          (singular to plural)
  $wealth/api/*                          → api/*
  $wealth/constants/*                    → constants/*
"""
from __future__ import annotations

import re
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
LIB_ROOT = PKG_ROOT / "src" / "lib"

# Ordered remap — longest prefix first.
PREFIX_MAP: list[tuple[str, str]] = [
    ("$wealth/components/screener/terminal/", "components/screener-terminal/"),
    ("$wealth/components/", "components/"),
    ("$wealth/stores/", "stores/"),
    ("$wealth/state/", "state/"),
    ("$wealth/types/", "types/"),
    ("$wealth/utils/", "utils/"),
    ("$wealth/util/", "utils/"),
    ("$wealth/api/", "api/"),
    ("$wealth/constants/", "constants/"),
]

IMPORT_RE = re.compile(r"""((?:from|import)\s*\(?\s*['"])(\$wealth/[^'"]+)(['"]\)?)""")

def relative_path(from_file: Path, target_subpath: str) -> str:
    """Compute relative path from from_file's dir to LIB_ROOT/target_subpath."""
    target = LIB_ROOT / target_subpath
    rel = Path(target).relative_to(LIB_ROOT)
    # walk from from_file.parent up to LIB_ROOT, then down to target
    up = len(from_file.parent.relative_to(LIB_ROOT).parts)
    if up == 0:
        prefix = "./"
    else:
        prefix = "../" * up
    return prefix + str(rel).replace("\\", "/")


def rewrite_spec(from_file: Path, spec: str) -> str:
    """spec is a $wealth/foo/bar path. Return relative path string."""
    for w_prefix, pkg_prefix in PREFIX_MAP:
        if spec.startswith(w_prefix):
            tail = spec[len(w_prefix):]
            target_subpath = pkg_prefix + tail
            return relative_path(from_file, target_subpath)
    return spec  # unchanged — caller will detect leftover


def process_file(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    changes = [0]

    def repl(m: re.Match[str]) -> str:
        pre, spec, post = m.group(1), m.group(2), m.group(3)
        new_spec = rewrite_spec(path, spec)
        if new_spec != spec:
            changes[0] += 1
        return pre + new_spec + post

    new_text = IMPORT_RE.sub(repl, text)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return changes[0]


def main() -> int:
    total = 0
    files_changed = 0
    exts = {".svelte", ".ts", ".tsx", ".js", ".mjs"}
    for p in LIB_ROOT.rglob("*"):
        if p.is_file() and p.suffix in exts:
            n = process_file(p)
            if n:
                files_changed += 1
                total += n

    # Verify zero leftovers.
    leftover_files: list[Path] = []
    leftover_re = re.compile(r"""['"]\$wealth/""")
    for p in LIB_ROOT.rglob("*"):
        if p.is_file() and p.suffix in exts:
            if leftover_re.search(p.read_text(encoding="utf-8")):
                leftover_files.append(p)

    print(f"Rewrote {total} imports across {files_changed} files")
    if leftover_files:
        print(f"LEFTOVER $wealth/ refs in {len(leftover_files)} files:")
        for p in leftover_files[:20]:
            print(f"  {p.relative_to(PKG_ROOT)}")
        return 1
    print("Zero $wealth/ leftovers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
