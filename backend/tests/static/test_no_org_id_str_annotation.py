import ast
from pathlib import Path


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
    """Static check: no route handler annotates ``org_id: str = Depends(get_org_id)``."""
    offenders: list[str] = []
    for path in Path("backend/app/domains").rglob("*.py"):
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
