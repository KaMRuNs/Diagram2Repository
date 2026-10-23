from pathlib import Path

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def render_prompt(name: str, **values: str) -> str:
    # str.replace, not str.format: prompts contain literal JSON braces.
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text
