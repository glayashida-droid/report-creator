"""App-level preferences (e.g. default tester name) stored beside project data."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from src.io.project_mirror import default_data_root

_PREFS_FILENAME = "user_prefs.json"
_YEAR_MIN = 2000
_YEAR_MAX = 2099


def user_prefs_path(data_root: Optional[Path] = None) -> Path:
    return (data_root or default_data_root()) / _PREFS_FILENAME


def load_user_prefs(data_root: Optional[Path] = None) -> dict:
    path = user_prefs_path(data_root)
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_user_prefs(prefs: dict, data_root: Optional[Path] = None) -> None:
    path = user_prefs_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


def default_tester_name(data_root: Optional[Path] = None) -> str:
    return (load_user_prefs(data_root).get("default_tester_name") or "").strip()


def save_default_tester_name(name: str, data_root: Optional[Path] = None) -> None:
    prefs = load_user_prefs(data_root)
    prefs["default_tester_name"] = (name or "").strip()
    save_user_prefs(prefs, data_root)


def parse_intranet_year(value) -> Optional[int]:
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if _YEAR_MIN <= year <= _YEAR_MAX:
        return year
    return None


def board_intranet_year(data_root: Optional[Path] = None) -> int:
    parsed = parse_intranet_year(load_user_prefs(data_root).get("board_intranet_year"))
    return parsed if parsed is not None else date.today().year


def save_board_intranet_year(year: int, data_root: Optional[Path] = None) -> None:
    parsed = parse_intranet_year(year)
    if parsed is None:
        return
    prefs = load_user_prefs(data_root)
    prefs["board_intranet_year"] = parsed
    save_user_prefs(prefs, data_root)
