"""The shipped pipeline.yaml must parse; endpoints/DSN come from env."""
import os
from pathlib import Path

import pytest

from phunter.config import ConfigError, load_config

CFG = Path(__file__).resolve().parents[1] / "config" / "pipeline.yaml"

ENV = {
    "PH_VL_BASE_URL": "http://vl.test:8080/v1",
    "PH_VL_MODEL": "vl-model",
    "PH_TEXT_BASE_URL": "http://text.test:8080/v1",
    "PH_TEXT_MODEL": "text-model",
    "PH_DB_DSN": "postgresql://u:p@db.test:5432/phunter",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


def test_shipped_config_parses():
    cfg = load_config(str(CFG))
    assert cfg.vl.base_url == ENV["PH_VL_BASE_URL"]  # env override wins
    assert cfg.prompts.ocr_system.strip()
    assert "Markdown" in cfg.prompts.ocr_user


def test_prompts_present_and_templated():
    cfg = load_config(str(CFG))
    assert "{ocr_text}" in cfg.prompts.structure_user
    assert "validate_json" in cfg.prompts.structure_system
    # block scalars must not swallow the JSON example braces
    assert '"total": number|null' in cfg.prompts.structure_system


def test_no_secrets_in_yaml():
    raw = CFG.read_text()
    for k in ENV:
        assert os.environ[k] not in raw
    assert "192.168." not in raw
    assert "postgresql://" not in raw


def test_missing_env_fails_fast(monkeypatch):
    monkeypatch.delenv("PH_DB_DSN")
    with pytest.raises(ConfigError, match="PH_DB_DSN"):
        load_config(str(CFG))
