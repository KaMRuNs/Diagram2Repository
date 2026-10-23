"""Data contracts shared by every pipeline stage.

Everything after stage 2 consumes only `Graph` and `ArchitectureSummary`, so the tools
are testable without any model.
"""

from typing import Literal

from pydantic import BaseModel, Field

NodeKind = Literal["service", "database", "cache", "queue", "gateway", "frontend", "external", "unknown"]
LicenseType = Literal["MIT", "Apache-2.0", "BSD-3-Clause"]


class Node(BaseModel):
    id: str = Field(description="unique slug, e.g. orders-api")
    label: str = Field(description="text written in the box")
    kind: NodeKind = "unknown"
    ports: list[int] = Field(default_factory=list)
    tech: str | None = Field(default=None, description="postgres, redis, node, fastapi, ...")


class Edge(BaseModel):
    source: str
    target: str
    label: str | None = None
    protocol: str | None = None


class Column(BaseModel):
    name: str
    type: str = "String"
    pk: bool = False
    fk: str | None = Field(default=None, description="referenced table.column, e.g. users.id")
    nullable: bool = True
    unique: bool = False


class Table(BaseModel):
    name: str
    columns: list[Column]


class Graph(BaseModel):
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)


class ArchitectureSummary(BaseModel):
    # Lenient defaults: small vision models sometimes drop a key, and a partial summary beats none.
    title: str = "Whiteboard Project"
    description: str = ""
    data_flow: str = ""
    recommended_stack: dict[str, str] = Field(default_factory=dict)


class StackChoice(BaseModel):
    """Chosen in the download dialog. "auto" keeps what was drawn/inferred per component."""

    backend: Literal["auto", "node", "python", "go"] = "auto"
    frontend: Literal["auto", "react", "static"] = "auto"
    database: Literal["auto", "postgres", "mysql"] = "auto"


class GenerateOptions(BaseModel):
    license_type: LicenseType = "MIT"
    author: str = "Your Name"
    project_name: str | None = None
    stack: StackChoice = Field(default_factory=StackChoice)


JobStatus = Literal[
    "queued", "preprocessing", "summarizing", "extracting", "normalizing", "generating", "done", "failed"
]
