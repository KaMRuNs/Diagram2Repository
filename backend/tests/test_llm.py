import pytest

from app.llm import extract_json, inline_schema, strip_think
from app.schemas import Graph


def test_strip_think():
    assert strip_think('<think>hmm {not json}</think>{"a": 1}') == '{"a": 1}'
    assert strip_think("dangling</think>ok") == "ok"


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        'Sure! Here it is:\n```json\n{"a": 1}\n```',
        '<think>let me see {x}</think>\nResult: {"a": 1} hope that helps',
        'prefix {"a": 1, "s": "brace } in \\"string\\""} suffix',
    ],
)
def test_extract_json_variants(text):
    assert extract_json(text)["a"] == 1


def test_extract_json_fails_cleanly():
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_inline_schema_keeps_title_property():
    from app.schemas import ArchitectureSummary

    schema = inline_schema(ArchitectureSummary)
    assert "title" in schema["properties"]  # a field literally named "title" must survive
    assert "title" not in schema  # ...while the schema's own title annotation is dropped


def test_inline_schema_has_no_refs():
    schema = inline_schema(Graph)
    assert "$defs" not in schema and "$ref" not in str(schema)
    kinds = schema["properties"]["nodes"]["items"]["properties"]["kind"]["enum"]
    assert "database" in kinds
