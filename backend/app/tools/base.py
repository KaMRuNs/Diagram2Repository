from pydantic import BaseModel, Field


class ToolOutput(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)
