import json
from pathlib import Path

import pytest

from app.pipeline.normalize import normalize_graph
from app.schemas import Column, Edge, Graph, Node, Table
from tests.conftest import load_sample


def test_infers_kinds_and_tech_from_labels():
    _, raw = load_sample("chat-app")
    graph, warnings = normalize_graph(raw)
    by_id = {n.id: n for n in graph.nodes}
    assert by_id["kafka"].kind == "queue" and by_id["kafka"].tech == "kafka"
    assert by_id["mongo"].tech == "mongodb"
    assert by_id["presence"].kind == "cache"
    assert by_id["mobile"].kind == "external"


def test_edges_resolve_labels_and_drop_unknown_endpoints():
    _, raw = load_sample("chat-app")
    graph, warnings = normalize_graph(raw)
    pairs = {(e.source, e.target) for e in graph.edges}
    assert ("ws", "kafka") in pairs  # source was written as the label "WS Gateway"
    assert not any("ghost" in t for _, t in pairs)
    assert any("ghost-node" in w for w in warnings)


def test_duplicate_ids_and_self_loops():
    raw = Graph(
        nodes=[Node(id="api", label="API"), Node(id="api", label="API")],
        edges=[
            Edge(source="api", target="api"),
            Edge(source="api", target="api-2"),
            Edge(source="api", target="api-2"),
        ],
    )
    graph, _ = normalize_graph(raw)
    assert [n.id for n in graph.nodes] == ["api", "api-2"]
    assert len(graph.edges) == 1


def test_tables_without_db_node_add_postgres():
    raw = Graph(tables=[Table(name="Users", columns=[Column(name="ID", type="INT", pk=True)])])
    graph, warnings = normalize_graph(raw)
    assert graph.tables[0].name == "users"
    assert graph.tables[0].columns[0].type == "Int"
    assert any(n.tech == "postgres" for n in graph.nodes)
    assert warnings


def test_fk_formats_are_normalized():
    raw = Graph(
        tables=[
            Table(
                name="orders",
                columns=[Column(name="user_id", fk="FK -> Users(id)"), Column(name="x", fk="users")],
            ),
            Table(name="users", columns=[Column(name="id", pk=True)]),
        ]
    )
    graph, _ = normalize_graph(raw)
    fks = [c.fk for c in graph.tables[0].columns]
    assert fks == ["users.id", "users.id"]


def test_real_qwen25vl_output_is_repaired():
    """Mistakes the 3B OCR model actually made on the test board."""
    data = json.loads((Path(__file__).parent / "fixtures" / "qwen25vl_board.json").read_text())
    data.pop("_comment")
    graph, warnings = normalize_graph(Graph.model_validate(data))
    by_id = {n.id: n for n in graph.nodes}
    # "Orders API" tagged gateway/"rest" must not become an nginx container
    assert by_id["orders-api"].kind == "service" and by_id["orders-api"].tech is None
    assert by_id["web-app"].kind == "frontend" and by_id["web-app"].tech == "react"
    # tables echoed as MySQL boxes are removed
    assert "users" not in by_id and "orders" not in by_id
    # FK moved from orders.id to orders.user_id
    cols = {c.name: c for c in graph.tables[1].columns}
    assert cols["user_id"].fk == "users.id" and cols["id"].fk is None
    assert any("Moved FK" in w for w in warnings)


def test_real_demo1_output_is_repaired():
    """Mistakes the 3B OCR model made on the real handwritten photo samples/demo1.jpg."""
    data = json.loads((Path(__file__).parent / "fixtures" / "qwen25vl_demo1.json").read_text())
    data.pop("_comment")
    graph, warnings = normalize_graph(Graph.model_validate(data))
    by_id = {n.id: n for n in graph.nodes}
    # roles are people, not containers
    assert by_id["user-admin"].kind == "external" and by_id["user-n"].kind == "external"
    assert by_id["web-server"].kind == "service"
    # invented table for the "User n" box is dropped, so no Postgres gets added for it
    assert graph.tables == []
    assert any("Ignored table 'user_n'" in w for w in warnings)
    # copied endpoint names and blanket "sql" are cleared from arrows
    assert all(e.label is None for e in graph.edges)
    # "sql" survives only on arrows touching a database ("Resident's Info" was read as one)
    dbs = {n.id for n in graph.nodes if n.kind == "database"}
    sql = [(e.source, e.target) for e in graph.edges if e.protocol == "sql"]
    assert sql and all(s in dbs or t in dbs for s, t in sql)
    assert ("user-n", "web-server") not in sql


def test_role_labels_vs_services():
    from app.pipeline.normalize import infer_kind_tech

    for label, kind in [
        ("Users", "external"),
        ("Customer 1", "external"),
        ("User Service", "service"),
        ("Admin Panel", "frontend"),
    ]:
        assert infer_kind_tech(Node(id="x", label=label, kind="unknown")).kind == kind, label


def test_empty_graph_raises():
    with pytest.raises(ValueError):
        normalize_graph(Graph())
