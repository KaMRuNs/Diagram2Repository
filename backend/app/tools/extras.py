from app.schemas import Node
from app.tools.base import ToolOutput
from app.tools.catalog import TECH, env_var_name, resolve_tech


def generate_env_and_makefile(
    nodes: list[Node],
    port_assignments: dict[str, int],
    primary_db: Node | None = None,
    has_tables: bool = False,
) -> ToolOutput:
    """`primary_db`: the SQL database the services use (host DATABASE_URL and `make db-shell`)."""
    env_lines = ["# Copy to .env and adjust. docker compose and Prisma both read it.", ""]
    seen: set[str] = set()
    db_node = (primary_db.id, resolve_tech(primary_db)) if primary_db else None

    env_lines.append("# Host ports")
    for n in nodes:
        tech = resolve_tech(n)
        if tech is None:
            continue
        env_lines.append(f"{env_var_name(n.id, 'PORT')}={port_assignments.get(n.id, TECH[tech].port)}")

    cred_lines: list[str] = []
    for n in nodes:
        tech = resolve_tech(n)
        for k, v in TECH[tech].env.items() if tech else ():
            if k not in seen:
                seen.add(k)
                cred_lines.append(f"{k}={v}")
    if cred_lines:
        env_lines += ["", "# Credentials", *cred_lines]

    if db_node:
        node_id, tech = db_node
        port = port_assignments.get(node_id, TECH[tech].port)
        url = (
            f"postgresql://app:app@localhost:{port}/app"
            if tech == "postgres"
            else f"mysql://root:app@localhost:{port}/app"
        )
        env_lines += ["", "# Used by Prisma / app code running on the host", f"DATABASE_URL={url}"]

    targets = [
        (
            "up",
            "Build and start all services",
            ["@test -f .env || cp .env.example .env", "docker compose up -d --build"],
        ),
        ("down", "Stop all services", ["docker compose down"]),
        ("logs", "Follow logs", ["docker compose logs -f"]),
        ("ps", "Show running services", ["docker compose ps"]),
        (
            "reset",
            "Stop and delete volumes" + (" (re-runs db/init.sql)" if has_tables else ""),
            ["docker compose down -v"],
        ),
    ]
    if db_node:
        node_id, tech = db_node
        cmd = (
            f'docker compose exec {node_id} psql -U "$${{POSTGRES_USER:-app}}" "$${{POSTGRES_DB:-app}}"'
            if tech == "postgres"
            else f"docker compose exec {node_id} mysql -uroot -p"
        )
        targets.append(("db-shell", "Open a database shell", [cmd]))

    mk = [".PHONY: " + " ".join(["help", *(t[0] for t in targets)]), "", "-include .env", "export", ""]
    mk += ["help:", '\t@echo "Targets:"']
    mk += [f'\t@echo "  {name:<9} {desc}"' for name, desc, _ in targets]
    for name, _, cmds in targets:
        mk += ["", f"{name}:", *(f"\t{c}" for c in cmds)]

    return ToolOutput(files={".env.example": "\n".join(env_lines) + "\n", "Makefile": "\n".join(mk) + "\n"})
