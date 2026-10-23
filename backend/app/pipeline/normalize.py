"""Deterministic clean-up of the raw OCR graph: ids, kinds, tech, edges, tables."""

import re

from app.schemas import Column, Edge, Graph, Node, Table
from app.tools.schema_gen import normalize_type, snake

# Specific technologies: trusted even if the model picked another kind.
_STRONG: list[tuple[str, str, str]] = [
    (r"postgres|postgresql|\bpg\b|psql", "database", "postgres"),
    (r"mysql|maria", "database", "mysql"),
    (r"mongo", "database", "mongodb"),
    (r"redis|memcache", "cache", "redis"),
    (r"kafka", "queue", "kafka"),
    (r"rabbit|amqp", "queue", "rabbitmq"),
    (r"\bs3\b|minio|bucket", "database", "minio"),
    (r"nginx|load ?balancer|\blb\b|ingress|reverse proxy", "gateway", "nginx"),
]
# Generic words: only used when the model said "unknown" or gave no tech.
_WEAK: list[tuple[str, str, str | None]] = [
    (r"stripe|paypal|twilio|sendgrid|auth0|third[- ]party|external|smtp|email provider", "external", None),
    (r"cache", "cache", "redis"),
    (r"queue|\bmq\b|sqs|pub ?/? ?sub|event bus|broker|stream", "queue", "rabbitmq"),
    (r"gateway|proxy", "gateway", "nginx"),
    (
        r"react|vue|angular|svelte|next\.?js|frontend|front-end|web ?app|\bui\b|dashboard|spa\b"
        r"|panel|portal|interface|console",
        "frontend",
        "react",
    ),
    (r"\bdb\b|database|\bsql\b|data ?store", "database", "postgres"),
    (r"express|node|nest", "service", "node"),
    (r"fastapi|flask|django|python", "service", "fastapi"),
    (r"golang|\bgo\b|\bgin\b", "service", "go"),
    (r"api|service|server|backend|worker|svc|auth|payment|order|job|cron", "service", None),
]
# People/roles, not services: "User", "Users", "User Admin", "User n", "Customer 1", "Mobile app".
_ACTOR = re.compile(
    r"^(end ?)?(user|customer|client|browser|mobile( app)?|actor|admin|guest|visitor)s?"
    r"( (admin|n|\d+|[a-z]))?$"
)
_GATEWAY_WORDS = re.compile(r"gateway|proxy|nginx|load ?balancer|\blb\b|ingress|traefik|envoy|kong")
# Protocols and generic words small models put in "tech"; they say nothing about the image to run.
_NOT_TECH = {
    "rest",
    "http",
    "https",
    "web",
    "api",
    "grpc",
    "sql",
    "tcp",
    "service",
    "server",
    "app",
    "backend",
    "frontend",
    "db",
    "database",
    "json",
    "microservice",
    "ui",
    "client",
    "none",
    "null",
    "unknown",
}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "node"


def infer_kind_tech(node: Node) -> Node:
    if node.tech and node.tech.strip().lower() in _NOT_TECH:
        node = node.model_copy(update={"tech": None})
    text = f"{node.label} {node.tech or ''}".lower()
    for pattern, kind, tech in _STRONG:
        if re.search(pattern, text):
            return node.model_copy(update={"kind": kind, "tech": tech})
    if _ACTOR.match(node.label.strip().lower()):
        return node.model_copy(update={"kind": "external", "tech": None})
    # Small VL models label any box called "... API" a gateway; trust the words on the board instead.
    if node.kind == "gateway" and not _GATEWAY_WORDS.search(text):
        node = node.model_copy(update={"kind": "unknown"})
    if node.kind != "unknown" and node.tech:
        return node
    for pattern, kind, tech in _WEAK:
        if re.search(pattern, text):
            return node.model_copy(
                update={
                    "kind": node.kind if node.kind != "unknown" else kind,
                    "tech": node.tech or tech,
                }
            )
    return node.model_copy(update={"kind": "service" if node.kind == "unknown" else node.kind})


def _normalize_fk(fk: str | None) -> str | None:
    if not fk:
        return None
    fk = re.sub(r"^(fk|ref(erences)?|->|→|=>)\s*", "", fk.strip(), flags=re.I)
    fk = fk.replace("(", ".").replace(")", "").replace(" ", "")
    table, _, col = fk.partition(".")
    return f"{snake(table)}.{snake(col)}" if col else f"{snake(table)}.id"


def _infer_fks(tables: list[Table], warnings: list[str]) -> None:
    """`user_id` -> users.id by convention, and undo FKs the model pinned on the wrong (pk) column."""
    names = {t.name for t in tables}

    def target_for(col: str) -> str | None:
        if not col.endswith("_id") or len(col) <= 3:
            return None
        base = col[:-3]
        candidates = [base, f"{base}s", f"{base}es"] + ([f"{base[:-1]}ies"] if base.endswith("y") else [])
        return next((c for c in candidates if c in names), None)

    for t in tables:
        inferred: dict[str, str] = {}
        for c in t.columns:
            ref = target_for(c.name)
            if not c.fk and ref and ref != t.name:
                c.fk = f"{ref}.id"
                inferred[ref] = c.name
        for c in t.columns:
            ref = c.fk.split(".")[0] if c.fk else None
            if c.pk and c.name == "id" and ref in inferred:
                warnings.append(f"Moved FK {c.fk} from {t.name}.id to {t.name}.{inferred[ref]}.")
                c.fk = None


def normalize_graph(graph: Graph) -> tuple[Graph, list[str]]:
    warnings: list[str] = []
    nodes: list[Node] = []
    lookup: dict[str, str] = {}
    used: set[str] = set()

    for raw in graph.nodes:
        label = (raw.label or raw.id or "").strip()
        if not label:
            continue
        base = slugify(raw.id or label)
        node_id, i = base, 2
        while node_id in used:
            node_id, i = f"{base}-{i}", i + 1
        used.add(node_id)
        ports = sorted({p for p in raw.ports if 0 < p < 65536})
        node = infer_kind_tech(raw.model_copy(update={"id": node_id, "label": label, "ports": ports}))
        nodes.append(node)
        for key in (raw.id, label, slugify(label), node_id):
            if key:
                lookup.setdefault(key.strip().lower(), node_id)

    edges: list[Edge] = []
    seen_edges: set[tuple[str, str]] = set()
    for e in graph.edges:
        src = lookup.get(e.source.strip().lower()) or lookup.get(slugify(e.source))
        dst = lookup.get(e.target.strip().lower()) or lookup.get(slugify(e.target))
        if not src or not dst:
            warnings.append(f"Dropped arrow {e.source!r} -> {e.target!r}: endpoint not found.")
            continue
        if src == dst or (src, dst) in seen_edges:
            continue
        seen_edges.add((src, dst))
        edges.append(e.model_copy(update={"source": src, "target": dst}))

    # The OCR model often copies an endpoint's name onto the arrow and tags every line "sql".
    labels = {n.id: n.label.strip().lower() for n in nodes}
    kinds = {n.id: n.kind for n in nodes}
    for e in edges:
        if e.label and e.label.strip().lower() in (labels[e.source], labels[e.target]):
            e.label = None
        if e.protocol == "sql" and "database" not in (kinds[e.source], kinds[e.target]):
            e.protocol = None

    tables: list[Table] = []
    seen_tables: set[str] = set()
    for t in graph.tables:
        name = snake(t.name)
        if name in seen_tables or not t.columns:
            continue
        seen_tables.add(name)
        cols: list[Column] = []
        seen_cols: set[str] = set()
        for c in t.columns:
            cname = snake(c.name)
            if cname in seen_cols:
                continue
            seen_cols.add(cname)
            cols.append(
                c.model_copy(
                    update={
                        "name": cname,
                        "type": normalize_type(c.type),
                        "fk": _normalize_fk(c.fk),
                    }
                )
            )
        tables.append(Table(name=name, columns=cols))
    _infer_fks(tables, warnings)

    connected = {e.source for e in edges} | {e.target for e in edges}
    # The OCR model invents a "schema" for a connected box (e.g. box "User n" -> table user_n with
    # id/name/email/password). A table named after a wired-up component is not on the board.
    connected_names = {snake(n.label) for n in nodes if n.id in connected}
    invented = [t for t in tables if t.name in connected_names]
    for t in invented:
        warnings.append(f"Ignored table '{t.name}': it repeats the '{t.name}' component, not a drawn table.")
    tables = [t for t in tables if t not in invented]

    # Real tables are sometimes also emitted as boxes; drop unconnected boxes that repeat a table name.
    table_names = {t.name for t in tables}
    kept: list[Node] = []
    for n in nodes:
        if n.id not in connected and snake(n.label) in table_names:
            warnings.append(f"Removed box '{n.label}': it is the '{snake(n.label)}' table, not a service.")
            continue
        kept.append(n)
    nodes = kept

    if tables and not any(n.kind == "database" and n.tech in ("postgres", "mysql", None) for n in nodes):
        db_id = "db" if "db" not in used else "postgres-db"
        nodes.append(Node(id=db_id, label="Postgres", kind="database", tech="postgres", ports=[5432]))
        warnings.append("Tables were found but no Postgres box; added a 'Postgres' database service.")

    if not nodes and not tables:
        raise ValueError("No boxes or tables could be read from the diagram.")
    return Graph(nodes=nodes, edges=edges, tables=tables), warnings
