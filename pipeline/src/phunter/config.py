"""YAML config + env overrides, pydantic-validated (display-digest pattern)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError


class ConfigError(Exception):
    pass


class LLMEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # base_url/model are deployment secrets: supply via PH_VL_*/PH_TEXT_*
    # env vars (see .env); load_config() fails fast when they end up empty.
    base_url: str = ""
    model: str = ""
    temperature: float = 0.0
    max_tokens: int = 3000
    timeout_s: float = 300.0
    retries: int = 2
    disable_thinking: bool = False
    use_tools: bool = False  # offer OpenAI-style tools (e.g. validate_json)


class ResizeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_pixels: int = 3_000_000
    jpeg_quality: int = 90


class DBConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dsn: str = ""  # via PH_DB_DSN (see .env / docker-compose.yaml)


class PromptsConfig(BaseModel):
    """LLM prompts, single source of truth = pipeline.yaml (no code defaults:
    a deployment must state explicitly what the model is told).
    structure_user may contain the {ocr_text} placeholder."""

    model_config = ConfigDict(extra="forbid")

    ocr_system: str
    ocr_user: str
    structure_system: str
    structure_user: str


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vl: LLMEndpoint
    text: LLMEndpoint
    resize: ResizeConfig = ResizeConfig()
    prompts: PromptsConfig
    db: DBConfig
    artifacts_dir: str = "/artifacts"
    # when the queue drains, the longest-waited failed request is requeued;
    # this caps how many times a single request may be retried (0 disables)
    max_request_retries: int = 3


def load_config(path: str | None = None) -> PipelineConfig:
    p = path or os.environ.get("PH_CONFIG", "config/pipeline.yaml")
    try:
        raw = yaml.safe_load(Path(p).read_text())
        cfg = PipelineConfig.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise ConfigError(f"config error ({p}): {e}") from e

    # apply env overrides explicitly (simple and readable)
    if os.environ.get("PH_VL_BASE_URL"):
        cfg.vl.base_url = os.environ["PH_VL_BASE_URL"]
    if os.environ.get("PH_VL_MODEL"):
        cfg.vl.model = os.environ["PH_VL_MODEL"]
    if os.environ.get("PH_TEXT_BASE_URL"):
        cfg.text.base_url = os.environ["PH_TEXT_BASE_URL"]
    if os.environ.get("PH_TEXT_MODEL"):
        cfg.text.model = os.environ["PH_TEXT_MODEL"]
    if os.environ.get("PH_DB_DSN"):
        cfg.db.dsn = os.environ["PH_DB_DSN"]
    if os.environ.get("PH_ARTIFACTS_DIR"):
        cfg.artifacts_dir = os.environ["PH_ARTIFACTS_DIR"]
    if os.environ.get("PH_MAX_REQUEST_RETRIES"):
        cfg.max_request_retries = int(os.environ["PH_MAX_REQUEST_RETRIES"])

    # endpoints/DSN are env-only now: refuse to start half-configured
    missing = [
        name
        for name, val in (
            ("PH_VL_BASE_URL", cfg.vl.base_url),
            ("PH_VL_MODEL", cfg.vl.model),
            ("PH_TEXT_BASE_URL", cfg.text.base_url),
            ("PH_TEXT_MODEL", cfg.text.model),
            ("PH_DB_DSN", cfg.db.dsn),
        )
        if not val
    ]
    if missing:
        raise ConfigError(f"missing required env var(s): {', '.join(missing)}")
    return cfg
