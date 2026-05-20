from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path("config/sources.yaml")


@lru_cache(maxsize=1)
def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)
