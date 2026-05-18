"""Canonical project paths. Single source of truth."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
RUBRICS_DIR = PROJECT_ROOT / "rubrics"
DEFAULT_KB_PATH = DATA_DIR / "knowledge.json"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DEFAULT_RUBRIC_PATH = RUBRICS_DIR / "arteta_v1.yaml"
