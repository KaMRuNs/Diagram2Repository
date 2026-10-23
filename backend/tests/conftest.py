import json
from pathlib import Path

import pytest

from app.pipeline.normalize import normalize_graph
from app.schemas import ArchitectureSummary, Graph

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def load_sample(name: str) -> tuple[ArchitectureSummary, Graph]:
    data = json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))
    return ArchitectureSummary.model_validate(data["summary"]), Graph.model_validate(data["graph"])


@pytest.fixture
def ecommerce() -> tuple[ArchitectureSummary, Graph]:
    summary, graph = load_sample("ecommerce")
    return summary, normalize_graph(graph)[0]


@pytest.fixture
def chat() -> tuple[ArchitectureSummary, Graph]:
    summary, graph = load_sample("chat-app")
    return summary, normalize_graph(graph)[0]
