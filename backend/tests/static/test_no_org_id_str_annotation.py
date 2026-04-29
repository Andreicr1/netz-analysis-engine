import ast
from pathlib import Path

# Resolve repo-root from this test file's location:
# backend/tests/static/test_no_org_id_str_annotation.py
#   parent[0] = backend/tests/static
#   parent[1] = backend/tests
#   parent[2] = backend
#   parent[3] = repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DOMAINS_ROOT = _REPO_ROOT / "backend" / "app" / "domains"


def _has_depends_get_org_id(default_node: ast.AST | None) -> bool:
    """Return True if the default is ``Depends(get_org_id)``."""
    if default_node is None:
        return False
    if not isinstance(default_node, ast.Call):
        return False
    func = default_node.func
    if isinstance(func, ast.Name) and func.id == "Depends":
        if default_node.args and isinstance(default_node.args[0], ast.Name):
            return default_node.args[0].id == "get_org_id"
    return False


def test_no_org_id_str_lying_annotation():
    """Static check: no route handler annotates ``org_id: str = Depends(get_org_id)``.

    Q108: path resolution anchored to __file__ so the guard works
    regardless of pytest cwd (repo root vs backend/).
    """
    assert _DOMAINS_ROOT.is_dir(), (
        f"_DOMAINS_ROOT must resolve to an existing directory. Got: {_DOMAINS_ROOT}"
    )
    offenders: list[str] = []
    for path in _DOMAINS_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            all_args = node.args.args + node.args.kwonlyargs
            defaults_offset = len(node.args.args) - len(node.args.defaults)
            all_defaults: list[ast.AST | None] = (
                [None] * defaults_offset + list(node.args.defaults)
                + list(node.args.kw_defaults)
            )
            for arg, default in zip(all_args, all_defaults, strict=False):
                if arg.arg != "org_id":
                    continue
                if not _has_depends_get_org_id(default):
                    continue
                if arg.annotation:
                    ann = ast.unparse(arg.annotation)
                    if ann == "str":
                        offenders.append(f"{path}:{arg.lineno}")
    assert not offenders, f"org_id: str = Depends(get_org_id) annotation lies remain: {offenders}"


def test_guard_path_resolves_to_real_directory():
    """Q108 invariant: _DOMAINS_ROOT must resolve to an existing dir
    independent of cwd. Catches the original bug where the guard scanned
    a non-existent path and passed vacuously."""
    assert _DOMAINS_ROOT.is_dir(), (
        f"_DOMAINS_ROOT must resolve regardless of cwd. Got: {_DOMAINS_ROOT}"
    )
    py_files = list(_DOMAINS_ROOT.rglob("*.py"))
    assert len(py_files) > 50, (
        f"Expected >50 Python files under app/domains, got {len(py_files)}. "
        "Path resolution likely broken."
    )
