import yaml

from app.schemas import Edge, Node
from app.tools.base import ToolOutput
from app.tools.catalog import TECH, env_var_name, resolve_tech
from app.tools.starters import starter_files

INFRA_KINDS = {"database", "cache", "queue"}


def _depends(a: str, b: str, deps: dict[str, set[str]]) -> bool:
    """True if `a` already (transitively) depends on `b`."""
    stack, seen = [a], set()
    while stack:
        cur = stack.pop()
        if cur == b:
            return True
        if cur not in seen:
            seen.add(cur)
            stack.extend(deps.get(cur, ()))
    return False


def dependency_pairs(nodes: list[Node], edges: list[Edge]) -> tuple[dict[str, set[str]], list[str]]:
    """Turn drawn arrows into `depends_on` (dependant -> dependencies).

    Arrows show data flow, not start order: "API -> Postgres" means API needs Postgres, but
    "Kafka -> Worker" also means Worker needs Kafka. Infra is always the dependency.
    """
    by_id = {n.id: n for n in nodes}
    deps: dict[str, set[str]] = {}
    warnings: list[str] = []
    for e in edges:
        src, dst = by_id.get(e.source), by_id.get(e.target)
        if not src or not dst or resolve_tech(src) is None or resolve_tech(dst) is None:
            continue
        if src.kind in INFRA_KINDS and dst.kind not in INFRA_KINDS:
            dependant, dependency = dst.id, src.id
        else:
            dependant, dependency = src.id, dst.id
        if dependant == dependency or dependency in deps.get(dependant, set()):
            continue
        if _depends(dependency, dependant, deps):
            warnings.append(f"Skipped depends_on {dependant} -> {dependency}: it would create a cycle.")
            continue
        deps.setdefault(dependant, set()).add(dependency)
    return deps, warnings


class _NoAliasDumper(yaml.SafeDumper):
    """Write shared lists (e.g. two Postgres healthchecks) in full instead of &id001/*id001."""

    def ignore_aliases(self, data) -> bool:
        return True


def internal_port(node: Node, port_assignments: dict[str, int]) -> int:
    """Port the service listens on inside the compose network."""
    spec = TECH[resolve_tech(node)]
    if spec.image:
        return spec.port
    return spec.container_port or port_assignments.get(node.id, spec.port)


def generate_docker_compose(
    nodes: list[Node],
    edges: list[Edge],
    port_assignments: dict[str, int],
    init_sql_db: str | None = None,
) -> ToolOutput:
    """`init_sql_db`: id of the SQL database that should load db/init.sql on first start."""
    out = ToolOutput()
    deps, out.warnings = dependency_pairs(nodes, edges)
    services: dict[str, dict] = {}
    volumes: dict[str, dict] = {}
    by_id = {n.id: n for n in nodes}

    for node in nodes:
        tech = resolve_tech(node)
        if tech is None:
            continue
        spec = TECH[tech]
        host_port = port_assignments.get(node.id, spec.port)
        container_port = internal_port(node, port_assignments)
        port_var = env_var_name(node.id, "PORT")
        svc: dict = {"image": spec.image} if spec.image else {"build": f"./services/{node.id}"}
        if spec.command:
            svc["command"] = spec.command
        svc["ports"] = [f"${{{port_var}:-{host_port}}}:{container_port}"]

        env = {k: f"${{{k}:-{v}}}" for k, v in spec.env.items()}
        env.update({k: v.replace("{id}", node.id) for k, v in spec.container_env.items()})
        if spec.custom and not spec.container_port:
            env["PORT"] = str(container_port)
        connections: list[str] = []
        for dep_id in sorted(deps.get(node.id, ())):
            dep = by_id[dep_id]
            dep_spec = TECH[resolve_tech(dep)]
            if dep_spec.connect_env:
                var, template = dep_spec.connect_env
                url = template.replace("{id}", dep_id)
            else:
                var = env_var_name(dep_id, "URL")
                url = f"http://{dep_id}:{internal_port(dep, port_assignments)}"
            if var in connections:
                var = env_var_name(dep_id, var)
            connections.append(var)
            env[var] = url
        if env:
            svc["environment"] = env

        if spec.custom:
            talks_to = [by_id[d].label for d in sorted(deps.get(node.id, ()))]
            files = starter_files(tech, node.id, node.label, container_port, connections, talks_to)
            out.files.update({f"services/{node.id}/{path}": body for path, body in files.items()})

        if spec.volume:
            vol = f"{node.id}-data"
            volumes[vol] = {}
            svc["volumes"] = [f"{vol}:{spec.volume}"]
        if node.id == init_sql_db:
            svc.setdefault("volumes", []).append("./db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro")
        if spec.healthcheck:
            svc["healthcheck"] = {"test": spec.healthcheck, "interval": "5s", "timeout": "5s", "retries": 10}

        if node.id in deps:
            svc["depends_on"] = {
                d: {
                    "condition": "service_healthy"
                    if TECH[resolve_tech(by_id[d])].healthcheck
                    else "service_started"
                }
                for d in sorted(deps[node.id])
            }
        svc["restart"] = "unless-stopped"
        services[node.id] = svc

    if not services:
        out.warnings.append("No containerisable services found; docker-compose.yml has no services.")
    doc: dict = {"services": services}
    if volumes:
        doc["volumes"] = volumes
    out.files["docker-compose.yml"] = yaml.dump(
        doc, Dumper=_NoAliasDumper, sort_keys=False, default_flow_style=False
    )
    out.data = {"services": list(services), "depends_on": {k: sorted(v) for k, v in deps.items()}}
    return out
