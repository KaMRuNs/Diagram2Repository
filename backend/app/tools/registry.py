"""Agent-facing tool definitions and dispatch.

Graph data is injected from job state (`ToolContext`) rather than passed as tool arguments:
a 4B model copying a large JSON graph into every call is slow and error-prone. The model
decides *what* to run and the few options; the tools read the authoritative graph.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from app.schemas import ArchitectureSummary, GenerateOptions, Graph, LicenseType, Node
from app.tools.base import ToolOutput
from app.tools.bundle import bundle_zip
from app.tools.catalog import resolve_tech
from app.tools.compose import generate_docker_compose
from app.tools.docs import generate_readme_and_license
from app.tools.extras import generate_env_and_makefile
from app.tools.ports import validate_port_conflicts
from app.tools.schema_gen import generate_db_schema
from app.tools.stack import primary_sql_db


@dataclass
class ToolContext:
    graph: Graph
    summary: ArchitectureSummary
    options: GenerateOptions = field(default_factory=GenerateOptions)
    files: dict[str, str] = field(default_factory=dict)
    port_assignments: dict[str, int] | None = None
    warnings: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    project_root: str = "project"
    zip_bytes: bytes | None = None
    download_url: str = ""


_PLACEHOLDER = re.compile(r"your|example|project[-_ ]?name|my[-_ ]?project|untitled|placeholder", re.I)


class NoArgs(BaseModel):
    pass


class ReadmeArgs(BaseModel):
    license_type: LicenseType | None = None
    project_name: str | None = None
    author: str | None = None


def _apply(ctx: ToolContext, name: str, out: ToolOutput) -> dict:
    ctx.files.update(out.files)
    ctx.warnings.extend(w for w in out.warnings if w not in ctx.warnings)
    if name not in ctx.completed:
        ctx.completed.append(name)
    return {"ok": True, "files_written": sorted(out.files), "warnings": out.warnings, **out.data}


def _ports(ctx: ToolContext, _: NoArgs) -> dict:
    report = validate_port_conflicts(ctx.graph.nodes)
    ctx.port_assignments = report.assignments
    return _apply(
        ctx,
        "validate_port_conflicts",
        ToolOutput(
            warnings=report.warnings, data={"assignments": report.assignments, "remapped": report.remapped}
        ),
    )


def _ensure_ports(ctx: ToolContext) -> dict[str, int]:
    if ctx.port_assignments is None:
        _ports(ctx, NoArgs())
    return ctx.port_assignments or {}


def _primary_db(ctx: ToolContext) -> Node | None:
    return primary_sql_db(ctx.graph.nodes, ctx.graph.edges)


def _compose(ctx: ToolContext, _: NoArgs) -> dict:
    db = _primary_db(ctx)
    init_db = db.id if db and ctx.graph.tables else None
    out = generate_docker_compose(ctx.graph.nodes, ctx.graph.edges, _ensure_ports(ctx), init_sql_db=init_db)
    return _apply(ctx, "generate_docker_compose", out)


def _schema(ctx: ToolContext, _: NoArgs) -> dict:
    db = _primary_db(ctx)
    provider = resolve_tech(db) if db else "postgres"
    return _apply(ctx, "generate_db_schema", generate_db_schema(ctx.graph.tables, provider))


def _readme(ctx: ToolContext, args: ReadmeArgs) -> dict:
    opts = ctx.options
    # Explicit user choices from the UI win over the model's suggestions.
    license_type = (
        opts.license_type
        if "license_type" in opts.model_fields_set
        else (args.license_type or opts.license_type)
    )
    # Author is a person's name: only the user supplies it. The model may name the project only when
    # the vision summary had no title, and never with a template placeholder like "your-project-name".
    author = opts.author
    model_name = (
        args.project_name if args.project_name and not _PLACEHOLDER.search(args.project_name) else None
    )
    untitled = ctx.summary.title == ArchitectureSummary().title
    project_name = opts.project_name or (model_name if untitled else None)
    out = generate_readme_and_license(
        ctx.summary,
        ctx.graph,
        _ensure_ports(ctx),
        sorted(ctx.files),
        license_type=license_type,
        author=author,
        project_name=project_name,
    )
    ctx.project_root = out.data["project_root"]
    return _apply(ctx, "generate_readme_and_license", out)


def _extras(ctx: ToolContext, _: NoArgs) -> dict:
    out = generate_env_and_makefile(
        ctx.graph.nodes, _ensure_ports(ctx), primary_db=_primary_db(ctx), has_tables=bool(ctx.graph.tables)
    )
    return _apply(ctx, "generate_env_and_makefile", out)


def _bundle(ctx: ToolContext, _: NoArgs) -> dict:
    missing = [t for t in required_tools(ctx) if t != "bundle_zip_download" and t not in ctx.completed]
    if missing:
        return {"ok": False, "error": f"Call these tools first: {', '.join(missing)}"}
    ctx.zip_bytes = bundle_zip(ctx.files, ctx.project_root)
    if "bundle_zip_download" not in ctx.completed:
        ctx.completed.append("bundle_zip_download")
    return {"ok": True, "download_url": ctx.download_url, "file_count": len(ctx.files)}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[ToolContext, BaseModel], dict]
    parameters: dict


_EMPTY = {"type": "object", "properties": {}, "required": []}

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "validate_port_conflicts",
            "Check every service from the extracted diagram for missing or duplicate host ports and "
            "assign a unique port to each. Call this first.",
            NoArgs,
            _ports,
            _EMPTY,
        ),
        Tool(
            "generate_docker_compose",
            "Write docker-compose.yml from the diagram's boxes and arrows (images, ports, depends_on, "
            "volumes, healthchecks).",
            NoArgs,
            _compose,
            _EMPTY,
        ),
        Tool(
            "generate_db_schema",
            "Write prisma/schema.prisma and db/init.sql from the tables drawn on the board. Only needed "
            "when the diagram contains tables.",
            NoArgs,
            _schema,
            _EMPTY,
        ),
        Tool(
            "generate_readme_and_license",
            "Write README.md (summary, Mermaid diagram, services, quickstart) and LICENSE.",
            ReadmeArgs,
            _readme,
            {
                "type": "object",
                "properties": {
                    "license_type": {"type": "string", "enum": ["MIT", "Apache-2.0", "BSD-3-Clause"]},
                    "project_name": {
                        "type": "string",
                        "description": "Short project name for the README title",
                    },
                    "author": {"type": "string"},
                },
                "required": [],
            },
        ),
        Tool(
            "generate_env_and_makefile",
            "Write .env.example (ports, credentials, DATABASE_URL) and a Makefile (up/down/logs/reset).",
            NoArgs,
            _extras,
            _EMPTY,
        ),
        Tool(
            "bundle_zip_download",
            "Zip all generated files into a downloadable repository. Call this last.",
            NoArgs,
            _bundle,
            _EMPTY,
        ),
    ]
}


def required_tools(ctx: ToolContext) -> list[str]:
    order = [
        "validate_port_conflicts",
        "generate_docker_compose",
        "generate_db_schema",
        "generate_readme_and_license",
        "generate_env_and_makefile",
        "bundle_zip_download",
    ]
    return [t for t in order if t != "generate_db_schema" or ctx.graph.tables]


def ollama_tool_specs() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in TOOLS.values()
    ]


def dispatch(ctx: ToolContext, name: str, arguments: dict | None) -> dict:
    tool = TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": f"Unknown tool '{name}'. Available: {', '.join(TOOLS)}"}
    try:
        args = tool.args_model.model_validate(arguments or {})
    except ValidationError as exc:
        return {"ok": False, "error": f"Invalid arguments: {exc.errors(include_url=False)}"}
    return tool.run(ctx, args)
