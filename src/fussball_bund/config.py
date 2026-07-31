"""配置加载：环境变量 + leagues.yaml。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


@dataclass
class Settings:
    odds_api_key: str = os.getenv("ODDS_API_KEY", "")
    football_data_org_key: str = os.getenv("FOOTBALL_DATA_ORG_KEY", "")
    db_path: str = os.getenv("DB_PATH", str(DATA_DIR / "fussball.db"))
    soccerdata_dir: str = os.getenv("SOCCERDATA_DIR", "~/.soccerdata_cache")
    # HTTP 通用
    request_timeout: int = 30
    request_retries: int = 3
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )


@dataclass
class LeagueConfig:
    key: str
    name: str
    name_en: str
    country: str
    football_data_uk: str
    odds_api: str
    fbref: str
    understat: str | None


def load_leagues() -> dict[str, LeagueConfig]:
    """加载 config/leagues.yaml，返回 {league_key: LeagueConfig}。"""
    path = CONFIG_DIR / "leagues.yaml"
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    leagues = {}
    for key, info in raw.get("leagues", {}).items():
        leagues[key] = LeagueConfig(
            key=key,
            name=info["name"],
            name_en=info["name_en"],
            country=info["country"],
            football_data_uk=info["football_data_uk"],
            odds_api=info["odds_api"],
            fbref=info["fbref"],
            understat=info.get("understat"),
        )
    return leagues


def load_default_seasons() -> list[str]:
    path = CONFIG_DIR / "leagues.yaml"
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return raw.get("default_seasons", ["2024-2025", "2025-2026"])


settings = Settings()
