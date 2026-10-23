from pydantic import BaseModel, Field

from app.schemas import Node
from app.tools.catalog import TECH, resolve_tech


class PortReport(BaseModel):
    assignments: dict[str, int] = Field(description="node id -> host port")
    remapped: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_port_conflicts(services: list[Node]) -> PortReport:
    """Give every containerised node a unique host port.

    Declared ports win, then the tech default; collisions are bumped to the next free port.
    """
    used: set[int] = set()
    report = PortReport(assignments={})
    for node in services:
        tech = resolve_tech(node)
        if tech is None:
            continue
        wanted = next((p for p in node.ports if 0 < p < 65536), TECH[tech].port)
        port = wanted
        while port in used:
            port += 1
        if port != wanted:
            report.remapped.append({"id": node.id, "from": wanted, "to": port})
            report.warnings.append(f"Port {wanted} of '{node.label}' already used; remapped to {port}.")
        used.add(port)
        report.assignments[node.id] = port
    return report
