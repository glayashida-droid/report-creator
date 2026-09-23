"""Run catalog reads and the board scan in a child process.

The child has its own GIL, so pandas, zip extraction, and JSON parsing do not
stall the interface process.
"""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from src.io.cancellable_process import ProcessCancelled, run_cancellable
from src.io.project_mirror import repo_root

_CATALOG_TIMEOUT_SEC = 45.0
_BOARD_TIMEOUT_SEC = 60.0


def _empty_catalog() -> dict:
    return {
        "standards_records": None,
        "standards_frame": None,
        "standard_images": {},
        "standards_mtime": None,
        "standards_error": "",
        "equipments_records": None,
        "equipments_frame": None,
        "equipments_mtime": None,
        "equipments_error": "",
    }


def isolated_load_catalogs(
    standards_path: Optional[str],
    equipment_path: Optional[str],
    *,
    timeout_sec: float = _CATALOG_TIMEOUT_SEC,
    run=subprocess.run,
    python_executable: Optional[str] = None,
    cancelled=None,
) -> dict:
    """Read the standards workbook and equipment list in a child process."""
    root = repo_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    payload = pickle.dumps(
        {
            "standards_path": standards_path or "",
            "equipment_path": equipment_path or "",
        }
    )
    try:
        completed = _run_child(
            run,
            [python_executable or sys.executable, str(Path(__file__).resolve()), "catalogs"],
            input=payload,
            timeout=max(float(timeout_sec), 0.1),
            env=env,
            cwd=str(root),
            cancelled=cancelled,
        )
    except ProcessCancelled:
        raise
    except subprocess.TimeoutExpired:
        out = _empty_catalog()
        out["standards_error"] = "读取标准库超时"
        out["equipments_error"] = "读取设备清单超时"
        return out
    if completed.returncode != 0:
        err = (completed.stderr or b"").decode("utf-8", "replace").strip() or "读取标准库失败"
        out = _empty_catalog()
        out["standards_error"] = err
        out["equipments_error"] = err
        return out
    try:
        data = pickle.loads(completed.stdout)
    except Exception as exc:
        out = _empty_catalog()
        out["standards_error"] = f"读取结果无法解析: {exc}"
        return out
    if not isinstance(data, dict):
        out = _empty_catalog()
        out["standards_error"] = "读取结果无法解析"
        return out
    return data


def isolated_list_board_rows(
    data_root: Optional[Path],
    *,
    today: date,
    timeout_sec: float = _BOARD_TIMEOUT_SEC,
    run=subprocess.run,
    python_executable: Optional[str] = None,
    cancelled=None,
):
    """Scan saved projects in a child process. Returns a list of BoardRow."""
    root = repo_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    payload = pickle.dumps(
        {
            "data_root": str(data_root) if data_root else "",
            "today": today.isoformat(),
        }
    )
    completed = _run_child(
        run,
        [python_executable or sys.executable, str(Path(__file__).resolve()), "board"],
        input=payload,
        timeout=max(float(timeout_sec), 0.1),
        env=env,
        cwd=str(root),
        cancelled=cancelled,
    )
    if completed.returncode != 0:
        err = (completed.stderr or b"").decode("utf-8", "replace").strip() or "看板扫描失败"
        raise RuntimeError(err)
    return pickle.loads(completed.stdout)


def _run_child(run, args, *, input, timeout, env, cwd, cancelled):
    if cancelled is None:
        return run(
            args,
            input=input,
            capture_output=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
            check=False,
        )
    return run_cancellable(
        args,
        input=input,
        timeout=timeout,
        env=env,
        cwd=cwd,
        cancelled=cancelled,
    )


def _load_catalogs_in_child(req: dict) -> dict:
    from src.parsers.db_loader import (
        BaseDataLoader,
        DuplicateStandardError,
        duplicate_standard_message,
    )

    out = _empty_catalog()
    std_path = req.get("standards_path") or ""
    eq_path = req.get("equipment_path") or ""
    loader = BaseDataLoader(
        standards_path=std_path or None,
        equipment_path=eq_path or None,
    )
    if std_path:
        try:
            loader.load_standards()
            frame = loader.standards_df
            out["standards_frame"] = frame
            out["standard_images"] = dict(loader._standard_images or {})
            out["standards_mtime"] = loader._standards_mtime
        except DuplicateStandardError as exc:
            out["standards_error"] = duplicate_standard_message(exc)
        except Exception as exc:
            out["standards_error"] = str(exc)
    if eq_path:
        try:
            loader.load_equipments()
            out["equipments_frame"] = loader.equipments_df
            out["equipments_mtime"] = loader._equipments_mtime
        except Exception as exc:
            out["equipments_error"] = str(exc)
    return out


def _load_board_in_child(req: dict):
    from src.io.project_board import list_board_rows

    raw_root = req.get("data_root") or ""
    when = date.fromisoformat(req["today"]) if req.get("today") else None
    root = Path(raw_root) if raw_root else None
    return list_board_rows(root, today=when)


def main(argv: list[str]) -> int:
    kind = argv[1] if len(argv) > 1 else ""
    req = pickle.loads(sys.stdin.buffer.read())
    if kind == "catalogs":
        pickle.dump(_load_catalogs_in_child(req), sys.stdout.buffer)
        return 0
    if kind == "board":
        pickle.dump(_load_board_in_child(req), sys.stdout.buffer)
        return 0
    print(f"unknown preload command: {kind}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
