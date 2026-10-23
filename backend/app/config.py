from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT_DIR / ".env", ".env"), extra="ignore")

    # "ollama": local models (default, offline). "hosted": an OpenAI-compatible provider serving
    # open-weight models; defaults target DigitalOcean Serverless Inference (model access key).
    llm_provider: Literal["ollama", "hosted"] = "ollama"
    hosted_base_url: str = "https://inference.do-ai.run/v1"
    hosted_api_key: str = ""

    ollama_base_url: str = "http://localhost:11434"
    vision_model: str = "gemma3:4b"
    ocr_model: str = "qwen2.5vl:3b"
    # qwen3:1.7b (hybrid) can switch thinking off. The installed qwen3:4b is the Thinking-2507 build,
    # which always reasons first: about 15 min per run on CPU instead of under a minute.
    agent_model: str = "qwen3:1.7b"

    agent_max_turns: int = 8
    agent_think: bool = False
    # Token caps per call: a tool call needs ~30 tokens; the OCR graph JSON ~1-2k.
    agent_num_predict: int = 256
    json_num_predict: int = 3072
    image_max_side: int = 1024
    llm_timeout: float = 600.0

    job_ttl_seconds: int = 3600
    samples_dir: Path = ROOT_DIR / "samples"
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
