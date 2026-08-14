"""配置管理：从 .env 和系统环境变量读取所有配置。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录
ROOT = Path(__file__).resolve().parents[1]

# 加载 .env（已存在则优先；不存在不报错）
load_dotenv(ROOT / ".env")

# ---- LLM Provider --------------------------------------------------------
PROVIDER: str = os.environ.get("PROVIDER", "mock").lower()

ERNIE_ENDPOINT: str = os.environ.get("ERNIE_ENDPOINT", "")
ERNIE_TOKEN: str = os.environ.get("ERNIE_TOKEN", "")
ERNIE_MODEL: str = os.environ.get("ERNIE_MODEL", "gpt-5.5")

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4o")

LLM_TIMEOUT_SECONDS: int = int(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))
LLM_MAX_RETRIES: int = int(os.environ.get("LLM_MAX_RETRIES", "3"))

# ---- 数据目录 -------------------------------------------------------------
DATA_DIR: Path = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
UPLOADS_DIR: Path = DATA_DIR / "uploads"
NORMALIZED_DIR: Path = DATA_DIR / "normalized"
REPORTS_DIR: Path = DATA_DIR / "reports"
LOGS_DIR: Path = DATA_DIR / "logs"
DB_PATH: Path = DATA_DIR / "evolution.db"

# 确保目录存在
for _d in (UPLOADS_DIR, NORMALIZED_DIR, REPORTS_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---- 评分范围（默认 0/1/2）------------------------------------------------
SCORE_RANGE: list[int] = [0, 1, 2]

# ---- 项目版本 -------------------------------------------------------------
VERSION: str = "0.1.0"
