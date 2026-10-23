"""Apply the user's stack choice to a graph, and pick the database the app actually uses."""

from app.schemas import Edge, Graph, Node, StackChoice
from app.tools.catalog import BACKEND_TECHS, FRONTEND_TECHS, SQL_TECHS, TECH, resolve_tech


def apply_stack(graph: Graph, stack: StackChoice) -> Graph:
    """Return a copy with tech overridden per category; the user's drawn graph stays untouched."""
    nodes: list[Node] = []
    for n in graph.nodes:
        tech = resolve_tech(n)
        if stack.frontend != "auto" and n.kind == "frontend" and tech and TECH[tech].custom:
            n = n.model_copy(update={"tech": stack.frontend})
        elif stack.backend != "auto" and tech in BACKEND_TECHS and n.kind != "frontend":
            n = n.model_copy(update={"tech": stack.backend})
        elif stack.database != "auto" and tech in SQL_TECHS:
            n = n.model_copy(update={"tech": stack.database})
        nodes.append(n)
    return graph.model_copy(update={"nodes": nodes})


def primary_sql_db(nodes: list[Node], edges: list[Edge]) -> Node | None:
    """The SQL database most components are wired to (gets init.sql, DATABASE_URL, db-shell)."""
    sql = [n for n in nodes if resolve_tech(n) in SQL_TECHS]
    if not sql:
        return None
    ids = {n.id for n in sql}
    wired = {i: 0 for i in ids}
    for e in edges:
        for end in (e.source, e.target):
            if end in ids:
                wired[end] += 1
    return max(sql, key=lambda n: wired[n.id])  # max() keeps the first on ties


def stack_summary(graph: Graph) -> dict[str, list[str]]:
    """Tech keys in use per category, for the README and the download dialog."""
    out: dict[str, list[str]] = {"backend": [], "frontend": [], "database": []}
    for n in graph.nodes:
        tech = resolve_tech(n)
        if tech in FRONTEND_TECHS and n.kind == "frontend":
            out["frontend"].append(tech)
        elif tech in BACKEND_TECHS:
            out["backend"].append(tech)
        elif tech in SQL_TECHS:
            out["database"].append(tech)
    return {k: sorted(set(v)) for k, v in out.items()}
