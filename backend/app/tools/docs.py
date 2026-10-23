import datetime as dt
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.schemas import ArchitectureSummary, Graph, LicenseType, Node
from app.tools.base import ToolOutput
from app.tools.catalog import TECH, resolve_tech
from app.tools.starters import STACK_LABELS

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES), keep_trailing_newline=True, autoescape=False)

_SHAPES = {
    "database": ('[("', '")]'),
    "cache": ('[("', '")]'),
    "queue": ('[["', '"]]'),
    "gateway": ('{{"', '"}}'),
    "frontend": ('(["', '"])'),
    "external": ('[/"', '"/]'),
}


def _mid(node_id: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in node_id)


def _mtext(text: str) -> str:
    return text.replace('"', "#quot;").replace("|", "/").strip()


def render_mermaid(graph: Graph, ports: dict[str, int] | None = None) -> str:
    lines = ["flowchart LR"]
    for n in graph.nodes:
        left, right = _SHAPES.get(n.kind, ('["', '"]'))
        port = (ports or {}).get(n.id) or (n.ports[0] if n.ports else None)
        label = _mtext(n.label) + (f" :{port}" if port else "")
        lines.append(f"  {_mid(n.id)}{left}{label}{right}")
    ids = {n.id for n in graph.nodes}
    for e in graph.edges:
        if e.source in ids and e.target in ids:
            arrow = f"-->|{_mtext(e.label)}|" if e.label else "-->"
            lines.append(f"  {_mid(e.source)} {arrow} {_mid(e.target)}")
    return "\n".join(lines)


def _tree(paths: list[str], root: str) -> str:
    lines = [f"{root}/"]
    for p in sorted(set(paths), key=lambda s: (s.count("/") > 0, s)):
        lines.append(f"├─ {p}")
    if len(lines) > 1:
        lines[-1] = lines[-1].replace("├─", "└─")
    return "\n".join(lines)


def _service_rows(nodes: list[Node], ports: dict[str, int]) -> list[dict]:
    rows = []
    for n in nodes:
        tech = resolve_tech(n)
        if tech is None:
            continue
        spec = TECH[tech]
        port = ports.get(n.id, spec.port)
        web = spec.custom or tech == "nginx" or n.kind in ("service", "frontend", "gateway")
        rows.append(
            {
                "id": n.id,
                "label": n.label,
                "kind": n.kind,
                "tech": STACK_LABELS.get(tech, tech),
                "runs_as": f"`{spec.image}`" if spec.image else f"build `services/{n.id}`",
                "url": f"http://localhost:{port}" if web else f"localhost:{port}",
            }
        )
    return rows


def license_text(license_type: LicenseType, author: str, year: int | None = None) -> str:
    text = (TEMPLATES / "licenses" / f"{license_type}.txt").read_text(encoding="utf-8")
    return text.replace("{year}", str(year or dt.date.today().year)).replace("{author}", author)


def generate_readme_and_license(
    summary: ArchitectureSummary,
    graph: Graph,
    port_assignments: dict[str, int],
    existing_files: list[str],
    license_type: LicenseType = "MIT",
    author: str = "Your Name",
    project_name: str | None = None,
) -> ToolOutput:
    year = dt.date.today().year
    title = project_name or summary.title
    root = "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-") or "project"
    readme = _env.get_template("README.md.j2").render(
        title=title,
        description=summary.description,
        data_flow=summary.data_flow,
        mermaid=render_mermaid(graph, port_assignments),
        services=_service_rows(graph.nodes, port_assignments),
        externals=[n.label for n in graph.nodes if n.kind == "external"],
        stack=summary.recommended_stack,
        tables=[{"name": t.name, "columns": [c.name for c in t.columns]} for t in graph.tables],
        tree=_tree([*existing_files, "README.md", "LICENSE", ".env.example", "Makefile"], root),
        license_type=license_type,
        year=year,
        author=author,
    )
    return ToolOutput(
        files={"README.md": readme, "LICENSE": license_text(license_type, author, year)},
        data={"license": license_type, "project_root": root},
    )
