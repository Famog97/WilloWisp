"""
M0.2 — Architecture guards (mechanical, CI-enforced).

Two structural invariants for the hexagon interior:
  1. The core must NOT import any UI / OS-automation toolkit (B9 / R-HEX).
  2. The core package must have NO internal import cycles (NR3).

Scoped to the existing kernel (`iscs_core`) and the new `core/` package once it
exists (M2+). The checks pass vacuously on an empty package, so they can be added
in M0 and tighten automatically as code migrates.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Packages that must stay UI/OS-toolkit-free and acyclic.
CORE_ROOTS = [r for r in ("iscs_core", "core") if (REPO / r).is_dir()]

# Native UI / OS-automation modules the core may never import.
FORBIDDEN = {"tkinter", "pyautogui", "keyboard"}


def _py_files(root: str):
    return sorted((REPO / root).rglob("*.py"))


def _module_name(path: Path) -> str:
    """Dotted module name; an __init__.py is named for its package."""
    rel = path.relative_to(REPO).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _toplevel_imports(path: Path) -> set[str]:
    """Top-level package names this file imports (for the toolkit ban)."""
    out: set[str] = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            out.add(n.module.split(".")[0])
    return out


def _intra_package_edges(path: Path, root: str) -> set[str]:
    """Dotted modules within `root` that this file imports (for cycle detection).
    Resolves both absolute (`root.x`) and relative (`from .x import`) imports."""
    pkg = _module_name(path)
    pkg_parts = pkg.split(".")
    edges: set[str] = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == root or a.name.startswith(root + "."):
                    edges.add(a.name)
        elif isinstance(n, ast.ImportFrom):
            if n.level == 0:
                if n.module and (n.module == root or n.module.startswith(root + ".")):
                    edges.add(n.module)
            else:
                # relative: climb `level` packages from this file's package
                base = pkg_parts[: len(pkg_parts) - (n.level - 1)] if not path.name == "__init__.py" \
                    else pkg_parts[: len(pkg_parts) - (n.level - 1)]
                target = base + ([n.module] if n.module else [])
                dotted = ".".join(target)
                if dotted == root or dotted.startswith(root + "."):
                    edges.add(dotted)
                # `from . import submod` — each name is a submodule of `base`
                if not n.module:
                    for a in n.names:
                        edges.add(".".join(base + [a.name]))
    # keep only edges that resolve to a real module in the package
    known = {_module_name(p) for p in _py_files(root)}
    return {e for e in edges if e in known and e != pkg}


def _find_cycle(graph: dict[str, set[str]]):
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack: list[str] = []

    def dfs(n):
        color[n] = GREY
        stack.append(n)
        for m in graph.get(n, ()):
            if color.get(m, BLACK) == GREY:
                return stack[stack.index(m):] + [m]
            if color.get(m, BLACK) == WHITE:
                c = dfs(m)
                if c:
                    return c
        color[n] = BLACK
        stack.pop()
        return None

    for n in graph:
        if color[n] == WHITE:
            c = dfs(n)
            if c:
                return c
    return None


@pytest.mark.parametrize("root", CORE_ROOTS)
def test_core_has_no_ui_or_os_toolkit_imports(root):
    offenders = {}
    for f in _py_files(root):
        bad = _toplevel_imports(f) & FORBIDDEN
        if bad:
            offenders[str(f.relative_to(REPO))] = sorted(bad)
    assert not offenders, f"core package {root!r} must not import UI/OS toolkits: {offenders}"


@pytest.mark.parametrize("root", CORE_ROOTS)
def test_core_package_is_acyclic(root):
    graph = {_module_name(f): _intra_package_edges(f, root) for f in _py_files(root)}
    cycle = _find_cycle(graph)
    assert cycle is None, f"import cycle in {root!r}: {' -> '.join(cycle)}"
