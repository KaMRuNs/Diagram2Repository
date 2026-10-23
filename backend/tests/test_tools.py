import io
import re
import zipfile

import yaml

from app.schemas import Column, Edge, Node, Table
from app.tools.bundle import bundle_zip
from app.tools.compose import generate_docker_compose
from app.tools.docs import generate_readme_and_license, license_text
from app.tools.extras import generate_env_and_makefile
from app.tools.ports import validate_port_conflicts
from app.tools.schema_gen import generate_db_schema, normalize_type
from app.tools.stack import primary_sql_db

# ---------- ports ----------


def test_port_conflicts_are_remapped(ecommerce):
    _, graph = ecommerce
    report = validate_port_conflicts(graph.nodes)
    ports = list(report.assignments.values())
    assert len(ports) == len(set(ports))
    assert report.assignments["storefront"] == 3000
    assert report.assignments["orders-api"] == 3001
    assert report.remapped == [{"id": "orders-api", "from": 3000, "to": 3001}]


def test_external_nodes_get_no_port(ecommerce):
    _, graph = ecommerce
    report = validate_port_conflicts(graph.nodes)
    assert "browser" not in report.assignments and "sendgrid" not in report.assignments


def test_default_ports_by_tech():
    report = validate_port_conflicts(
        [Node(id="db", label="db", kind="database", tech="postgres"), Node(id="c", label="c", kind="cache")]
    )
    assert report.assignments == {"db": 5432, "c": 6379}


# ---------- compose ----------


def _compose(graph):
    ports = validate_port_conflicts(graph.nodes).assignments
    db = primary_sql_db(graph.nodes, graph.edges)
    init_db = db.id if db and graph.tables else None
    out = generate_docker_compose(graph.nodes, graph.edges, ports, init_sql_db=init_db)
    return yaml.safe_load(out.files["docker-compose.yml"]), out


def test_compose_has_no_yaml_aliases():
    nodes = [Node(id="a", label="A", kind="database"), Node(id="b", label="B", kind="database")]
    text = generate_docker_compose(nodes, [], {"a": 5432, "b": 5433}).files["docker-compose.yml"]
    assert "&id" not in text and "*id" not in text


def test_compose_parses_and_has_unique_host_ports(ecommerce):
    doc, _ = _compose(ecommerce[1])
    host_ports = [re.search(r":-(\d+)}", p).group(1) for s in doc["services"].values() for p in s["ports"]]
    assert len(host_ports) == len(set(host_ports))
    assert "browser" not in doc["services"]


def test_compose_depends_on_follows_data_flow(ecommerce):
    doc, _ = _compose(ecommerce[1])
    s = doc["services"]
    assert set(s["orders-api"]["depends_on"]) == {"orders-db", "cache", "queue"}
    # "queue -> email-worker" arrow: the worker depends on the queue, not the other way round
    assert "queue" in s["email-worker"]["depends_on"]
    assert "depends_on" not in s["queue"]
    assert s["orders-api"]["depends_on"]["orders-db"]["condition"] == "service_healthy"


def test_compose_injects_connection_urls_and_init_sql(ecommerce):
    doc, out = _compose(ecommerce[1])
    api_env = doc["services"]["orders-api"]["environment"]
    assert "@orders-db:5432/" in api_env["DATABASE_URL"]
    assert api_env["REDIS_URL"] == "redis://cache:6379"
    assert any("init.sql" in v for v in doc["services"]["orders-db"]["volumes"])
    # express -> Node starter app on its remapped port, aware of its injected connections
    assert "3001" in out.files["services/orders-api/Dockerfile"]
    index = out.files["services/orders-api/src/index.js"]
    assert '"DATABASE_URL"' in index and '"REDIS_URL"' in index and "/health" in index
    assert "fastapi" in out.files["services/email-worker/requirements.txt"]
    assert "services/storefront/src/App.jsx" in out.files


def test_compose_skips_cycles():
    nodes = [Node(id="a", label="A", kind="service"), Node(id="b", label="B", kind="service")]
    out = generate_docker_compose(nodes, [Edge(source="a", target="b"), Edge(source="b", target="a")], {})
    doc = yaml.safe_load(out.files["docker-compose.yml"])
    assert "depends_on" in doc["services"]["a"] and "depends_on" not in doc["services"]["b"]
    assert any("cycle" in w for w in out.warnings)


def test_kafka_advertises_service_name(chat):
    doc, _ = _compose(chat[1])
    assert doc["services"]["kafka"]["environment"]["KAFKA_ADVERTISED_LISTENERS"] == "PLAINTEXT://kafka:9092"
    assert doc["services"]["history"]["environment"]["KAFKA_BROKERS"] == "kafka:9092"


# ---------- schema ----------


def test_schema_contains_every_table_and_fk(ecommerce):
    out = generate_db_schema(ecommerce[1].tables)
    prisma, sql = out.files["prisma/schema.prisma"], out.files["db/init.sql"]
    for t in ("users", "books", "orders", "order_items"):
        assert f'CREATE TABLE IF NOT EXISTS "{t}"' in sql
        assert f'@@map("{t}")' in prisma
    assert sql.count("FOREIGN KEY") == 3
    assert '@relation("Orders_user_id", fields: [user_id], references: [id])' in prisma
    assert "orders Orders[]" in prisma
    assert "@@id([order_id, book_id])" in prisma
    assert 'PRIMARY KEY ("order_id", "book_id")' in sql


def test_schema_fk_type_follows_referenced_pk(ecommerce):
    sql = generate_db_schema(ecommerce[1].tables).files["db/init.sql"]
    assert '"user_id" UUID NOT NULL' in sql


def test_schema_adds_missing_pk_and_drops_bad_fk():
    tables = [Table(name="notes", columns=[Column(name="body"), Column(name="owner", fk="people.id")])]
    out = generate_db_schema(tables)
    assert '"id" SERIAL PRIMARY KEY' in out.files["db/init.sql"]
    assert "FOREIGN KEY" not in out.files["db/init.sql"]
    assert any("people" in w for w in out.warnings)


def test_normalize_type():
    assert normalize_type("VARCHAR(255)") == "String"
    assert normalize_type("bigint") == "BigInt"
    assert normalize_type("timestamptz") == "DateTime"
    assert normalize_type("uuid") == "Uuid"
    assert normalize_type("weird") == "String"


# ---------- docs / extras / bundle ----------


def test_readme_and_license(ecommerce):
    summary, graph = ecommerce
    ports = validate_port_conflicts(graph.nodes).assignments
    out = generate_readme_and_license(
        summary, graph, ports, ["docker-compose.yml"], license_type="Apache-2.0", author="Ada"
    )
    readme = out.files["README.md"]
    assert readme.startswith("# Online Bookstore")
    assert "```mermaid" in readme and "Orders API :3001" in readme
    assert "| `users` |" in readme
    assert "Apache License" in out.files["LICENSE"] and "Ada" in out.files["LICENSE"]
    assert out.data["project_root"] == "online-bookstore"


def test_license_texts_have_no_placeholders():
    for lic in ("MIT", "Apache-2.0", "BSD-3-Clause"):
        text = license_text(lic, "Ada", 2026)
        assert "{year}" not in text and "{author}" not in text and "2026" in text


def test_env_and_makefile(ecommerce):
    _, graph = ecommerce
    ports = validate_port_conflicts(graph.nodes).assignments
    db = primary_sql_db(graph.nodes, graph.edges)
    out = generate_env_and_makefile(graph.nodes, ports, primary_db=db, has_tables=True)
    env, mk = out.files[".env.example"], out.files["Makefile"]
    assert "ORDERS_API_PORT=3001" in env and "POSTGRES_PASSWORD=app" in env
    assert "DATABASE_URL=postgresql://app:app@localhost:5432/app" in env
    assert "\tdocker compose up -d --build" in mk  # recipes must be tab-indented
    assert "db-shell:" in mk and "re-runs db/init.sql" in mk


def test_primary_db_is_the_one_services_use():
    """demo1.jpg case: 'Resident's Info' (unwired Postgres) must not win over the wired 'Database'."""
    nodes = [
        Node(id="resident-info", label="Resident's Info", kind="database"),
        Node(id="web-server", label="Web Server", kind="service"),
        Node(id="database", label="Database", kind="database"),
    ]
    edges = [Edge(source="web-server", target="database")]
    db = primary_sql_db(nodes, edges)
    assert db.id == "database"
    out = generate_env_and_makefile(nodes, {"resident-info": 5432, "database": 5433}, primary_db=db)
    assert "localhost:5433" in out.files[".env.example"]
    assert "exec database psql" in out.files["Makefile"]
    assert "init.sql" not in out.files["Makefile"]


# ---------- stack choice ----------


def test_stack_choice_rewrites_services(ecommerce):
    from app.schemas import StackChoice
    from app.tools.stack import apply_stack

    _, graph = ecommerce
    g = apply_stack(graph, StackChoice(backend="go", frontend="static", database="mysql"))
    by_id = {n.id: n for n in g.nodes}
    assert by_id["orders-api"].tech == by_id["email-worker"].tech == "go"
    assert by_id["storefront"].tech == "static"
    assert by_id["orders-db"].tech == "mysql"
    assert by_id["cache"].tech == "redis" and by_id["gateway"].tech in (None, "nginx")  # infra untouched
    assert {n.id: n.tech for n in graph.nodes}["orders-api"] == "express"  # original not mutated

    doc, out = _compose(g)
    assert doc["services"]["orders-db"]["image"] == "mysql:8.4"
    assert "mysql://" in doc["services"]["orders-api"]["environment"]["DATABASE_URL"]
    assert "services/orders-api/main.go" in out.files
    assert doc["services"]["storefront"]["ports"] == ["${STOREFRONT_PORT:-3000}:80"]  # nginx inside

    schema = generate_db_schema(g.tables, "mysql")
    sql, prisma = schema.files["db/init.sql"], schema.files["prisma/schema.prisma"]
    assert "`id` INT AUTO_INCREMENT PRIMARY KEY" in sql
    assert "`email` VARCHAR(191) NOT NULL UNIQUE" in sql
    assert 'provider = "mysql"' in prisma and "@db.Char(36)" in prisma and "@db.Uuid" not in prisma


def test_bundle_zip_roundtrip():
    data = bundle_zip({"README.md": "hi", "db/init.sql": "--"}, "proj")
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert names == ["proj/README.md", "proj/db/init.sql"]
