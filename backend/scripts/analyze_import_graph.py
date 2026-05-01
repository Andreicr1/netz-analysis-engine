"""Build and analyze the Netz import dependency graph with NetworkX.

Walks ``backend/{app, ai_engine, quant_engine, vertical_engines, data_providers}``,
parses every ``import`` / ``from ... import`` statement via ``ast``, and emits a
package-level ``DiGraph`` plus violation reports against the import-linter
contracts in ``pyproject.toml``.

Outputs (under ``reports/import_graph/``):
- ``modules.graphml``        — full module-level DAG (one node per .py file)
- ``packages.graphml``       — collapsed package-level DAG (one node per layer)
- ``packages.png``           — visualization with architectural layers
- ``violations.txt``         — concrete edges that break the 4 contracts
- ``centrality.csv``         — in/out degree + PageRank per package
"""

from __future__ import annotations

import ast
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterator

import matplotlib.pyplot as plt
import networkx as nx

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
OUTPUT_DIR = REPO_ROOT / "reports" / "import_graph"

ROOTS = ["app", "ai_engine", "quant_engine", "vertical_engines", "data_providers"]
LAYER_DEPTH = 3
PACKAGE_LAYERS = {
    "app.core": "core",
    "app.domains.credit": "domains/credit",
    "app.domains.wealth": "domains/wealth",
    "app.services": "services",
    "app.workers": "workers",
    "ai_engine": "ai_engine",
    "quant_engine": "quant_engine",
    "vertical_engines.base": "verticals/base",
    "vertical_engines.credit": "verticals/credit",
    "vertical_engines.wealth": "verticals/wealth",
    "data_providers": "data_providers",
}


def iter_python_files() -> Iterator[Path]:
    for root in ROOTS:
        yield from (BACKEND_ROOT / root).rglob("*.py")


def module_path(path: Path) -> str:
    rel = path.relative_to(BACKEND_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def collapse_to_package(module: str, depth: int = LAYER_DEPTH) -> str:
    parts = module.split(".")
    if parts[0] in {"app"} and len(parts) >= 3:
        return ".".join(parts[: min(len(parts), depth)])
    return ".".join(parts[: min(len(parts), depth)])


def parse_imports(path: Path, current_module: str) -> set[str]:
    """Return the set of fully-qualified module names imported by ``path``.

    Relative-import resolution must distinguish ``__init__.py`` (where the
    module name IS the package) from regular modules (where the module's own
    segment must be stripped to obtain the package).  Without this, level-1
    imports inside ``pkg/__init__.py`` were resolved to ``.x`` and silently
    dropped by ``is_internal``, hiding real cross-package edges.
    """
    is_init = path.name == "__init__.py"

    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import
                base_parts = current_module.split(".") if current_module else []
                # For __init__.py, current_module equals the package name, so
                # level=1 means "self"; for regular modules, level=1 strips the
                # module's own segment.  Subtract one stripping step for packages.
                levels_to_strip = node.level - (1 if is_init else 0)
                if levels_to_strip <= 0:
                    base = current_module
                elif levels_to_strip <= len(base_parts):
                    base = ".".join(base_parts[:-levels_to_strip])
                else:
                    base = ""
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            if target:
                imports.add(target)
                for alias in node.names:
                    imports.add(f"{target}.{alias.name}")
    return imports


def is_internal(module: str) -> bool:
    head = module.split(".", 1)[0]
    return head in ROOTS


def build_module_graph() -> nx.DiGraph:
    g: nx.DiGraph = nx.DiGraph()
    for py in iter_python_files():
        src = module_path(py)
        if not src:
            continue
        g.add_node(src)
        for tgt in parse_imports(py, src):
            if not is_internal(tgt):
                continue
            if tgt == src:
                continue
            g.add_edge(src, tgt)
    return g


def collapse_graph(module_graph: nx.DiGraph) -> nx.DiGraph:
    pkg: nx.DiGraph = nx.DiGraph()
    for u, v in module_graph.edges():
        pu, pv = collapse_to_package(u), collapse_to_package(v)
        if pu == pv:
            continue
        if pkg.has_edge(pu, pv):
            pkg[pu][pv]["weight"] += 1
        else:
            pkg.add_edge(pu, pv, weight=1)
    return pkg


def detect_violations(module_graph: nx.DiGraph) -> dict[str, list[tuple[str, str]]]:
    """Return concrete edges that violate the 4 import-linter contracts."""
    v: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for u, t in module_graph.edges():
        # 1. Verticals must not import each other
        if u.startswith("vertical_engines.credit") and t.startswith("vertical_engines.wealth"):
            v["cross_vertical"].append((u, t))
        if u.startswith("vertical_engines.wealth") and t.startswith("vertical_engines.credit"):
            v["cross_vertical"].append((u, t))

        # 2. models must not import service (credit + wealth)
        if u.endswith(".models") and (t.endswith(".service") or t.endswith(".dd_report_engine") or t.endswith(".fact_sheet_engine")):
            up = ".".join(u.split(".")[:-1])
            tp = ".".join(t.split(".")[:-1])
            if up == tp and (u.startswith("vertical_engines.credit") or u.startswith("vertical_engines.wealth")):
                v["models_to_service"].append((u, t))

        # 3. helpers (any sibling of service) must not import service
        if (t.endswith(".service") or t.endswith(".dd_report_engine") or t.endswith(".fact_sheet_engine")) and \
           (u.startswith("vertical_engines.credit") or u.startswith("vertical_engines.wealth")):
            up_parts = u.split(".")
            tp_parts = t.split(".")
            if len(up_parts) >= 4 and len(tp_parts) >= 4 and up_parts[:3] == tp_parts[:3]:
                if up_parts[3] != tp_parts[3]:
                    v["helpers_to_service"].append((u, t))

        # 4. quant_engine vertical-agnostic services must not import app.domains.*
        if u.startswith("quant_engine.") and (t.startswith("app.domains.wealth") or t.startswith("app.domains.credit")):
            v["quant_to_domain"].append((u, t))
    return v


def layer_for(pkg: str) -> str:
    for prefix, layer in PACKAGE_LAYERS.items():
        if pkg == prefix or pkg.startswith(prefix + "."):
            return layer
    return pkg.split(".", 1)[0]


def visualize(pkg_graph: nx.DiGraph, out_path: Path) -> None:
    layer_color = {
        "core": "#94a3b8",
        "domains/credit": "#fb923c",
        "domains/wealth": "#60a5fa",
        "services": "#a78bfa",
        "workers": "#f472b6",
        "ai_engine": "#34d399",
        "quant_engine": "#facc15",
        "verticals/base": "#cbd5e1",
        "verticals/credit": "#ea580c",
        "verticals/wealth": "#2563eb",
        "data_providers": "#10b981",
    }
    nodes = list(pkg_graph.nodes())
    colors = [layer_color.get(layer_for(n), "#9ca3af") for n in nodes]
    sizes = [200 + 80 * pkg_graph.degree(n) for n in nodes]

    plt.figure(figsize=(20, 14))
    pos = nx.spring_layout(pkg_graph, seed=42, k=1.4, iterations=80)

    weights = [pkg_graph[u][v]["weight"] for u, v in pkg_graph.edges()]
    max_w = max(weights) if weights else 1
    edge_widths = [0.3 + 2.5 * w / max_w for w in weights]

    nx.draw_networkx_edges(pkg_graph, pos, alpha=0.25, width=edge_widths,
                           edge_color="#475569", arrowsize=8, arrows=True)
    nx.draw_networkx_nodes(pkg_graph, pos, node_color=colors, node_size=sizes,
                           edgecolors="#1e293b", linewidths=0.6)
    labels = {n: n.split(".")[-1] for n in nodes}
    nx.draw_networkx_labels(pkg_graph, pos, labels=labels, font_size=7,
                            font_color="#0f172a")

    legend = [plt.Line2D([0], [0], marker="o", color="w", label=lbl,
                         markerfacecolor=clr, markersize=10)
              for lbl, clr in layer_color.items()]
    plt.legend(handles=legend, loc="upper left", fontsize=8, frameon=False)
    plt.title(f"Netz import graph — {pkg_graph.number_of_nodes()} packages, "
              f"{pkg_graph.number_of_edges()} edges", fontsize=14)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close()


def write_centrality(pkg_graph: nx.DiGraph, out_path: Path) -> None:
    pr = nx.pagerank(pkg_graph, alpha=0.85)
    rows = sorted(
        (
            {
                "package": n,
                "in_degree": pkg_graph.in_degree(n),
                "out_degree": pkg_graph.out_degree(n),
                "pagerank": round(pr[n], 5),
            }
            for n in pkg_graph.nodes()
        ),
        key=lambda r: r["pagerank"],
        reverse=True,
    )
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["package", "in_degree", "out_degree", "pagerank"])
        writer.writeheader()
        writer.writerows(rows)


def write_violations(violations: dict[str, list[tuple[str, str]]], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for kind, edges in violations.items():
            f.write(f"# {kind} ({len(edges)} edges)\n")
            for u, t in sorted(set(edges)):
                f.write(f"  {u} -> {t}\n")
            f.write("\n")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[1/5] scanning {BACKEND_ROOT}…")
    module_graph = build_module_graph()
    print(f"      modules: {module_graph.number_of_nodes()}  edges: {module_graph.number_of_edges()}")

    print("[2/5] collapsing to package-level graph…")
    pkg_graph = collapse_graph(module_graph)
    print(f"      packages: {pkg_graph.number_of_nodes()}  edges: {pkg_graph.number_of_edges()}")

    print("[3/5] writing graphml…")
    nx.write_graphml(module_graph, OUTPUT_DIR / "modules.graphml")
    nx.write_graphml(pkg_graph, OUTPUT_DIR / "packages.graphml")

    print("[4/5] visualizing package graph…")
    visualize(pkg_graph, OUTPUT_DIR / "packages.png")

    print("[5/5] computing centrality + checking violations…")
    write_centrality(pkg_graph, OUTPUT_DIR / "centrality.csv")
    violations = detect_violations(module_graph)
    write_violations(violations, OUTPUT_DIR / "violations.txt")

    total_violations = sum(len(v) for v in violations.values())
    summary = ", ".join(f"{k}={len(v)}" for k, v in violations.items()) or "none"
    print(f"\nDone. Outputs in {OUTPUT_DIR.relative_to(REPO_ROOT)}/")
    print(f"  violations: {summary}")
    print(f"  cycles in package graph: {sum(1 for _ in nx.simple_cycles(pkg_graph))}")
    return 0 if total_violations == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
