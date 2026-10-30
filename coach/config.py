"""Loads config.yaml and .env, and answers score/target lookups."""
import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def path(key: str) -> Path:
    return ROOT / load_config()["paths"][key]


def active_provider_name() -> str:
    return os.getenv("PROVIDER", "deepseek").strip().lower() or "deepseek"


def band_for(score: int) -> dict:
    for band in load_config()["score_bands"]:
        if score in band["scores"]:
            return band
    raise ValueError(f"No score band configured for score {score}")


def features_for(score: int) -> list[str]:
    """Cumulative features: every band up to and including this score's band."""
    features = []
    for band in load_config()["score_bands"]:
        if min(band["scores"]) <= score:
            features.extend(band["features"])
    return features


def target_for(key: str) -> dict:
    for target in load_config()["targets"]:
        if target["key"] == key:
            return target
    raise ValueError(f"Unknown target AI: {key}")
