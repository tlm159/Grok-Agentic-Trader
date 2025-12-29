import json
from pathlib import Path

DEFAULT_PATH = Path("config/settings.json")


def load_config(path=DEFAULT_PATH):
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config file: {config_path}")
    return json.loads(config_path.read_text())


def resolve_path(path_value):
    return Path(path_value).expanduser().resolve()
