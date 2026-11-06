"""Settings, portfolio and cache live in %APPDATA%\\StockSense.

Installing a new version over the old one never touches this folder, so the
keys, the portfolio and past analyses survive upgrades."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from . import APP_NAME, secure


def config_dir() -> str:
    override = os.environ.get("STOCKSENSE_CONFIG_DIR")
    if override:
        d = override
    else:
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
        d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def read_json(name: str, default):
    try:
        with open(os.path.join(config_dir(), name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(name: str, data) -> None:
    path = os.path.join(config_dir(), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


@dataclass
class Settings:
    gemini_blob: str = ""        # Gemini key, encrypted with Windows DPAPI
    finnhub_blob: str = ""       # Finnhub key, encrypted with Windows DPAPI
    last_ticker: str = ""
    first_run_done: bool = False

    # ---- keys (stored encrypted, read in plain text only in memory)
    @property
    def gemini_key(self) -> str:
        return secure.unprotect(self.gemini_blob)

    @gemini_key.setter
    def gemini_key(self, v: str) -> None:
        self.gemini_blob = secure.protect(v.strip()) if v.strip() else ""

    @property
    def finnhub_key(self) -> str:
        return secure.unprotect(self.finnhub_blob)

    @finnhub_key.setter
    def finnhub_key(self, v: str) -> None:
        self.finnhub_blob = secure.protect(v.strip()) if v.strip() else ""

    @property
    def keys_ready(self) -> bool:
        return bool(self.gemini_key and self.finnhub_key)

    @classmethod
    def load(cls) -> "Settings":
        data = read_json("settings.json", {})
        if not isinstance(data, dict):
            data = {}
        try:
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception:
            return cls()

    def save(self) -> None:
        write_json("settings.json", asdict(self))
