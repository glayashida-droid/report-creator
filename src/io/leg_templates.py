"""Save and load reusable Leg layouts, independent of any project mirror."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from src.io.project_mirror import default_data_root
from src.models.project_state import ProjectState, TestLeg, TestNode, TestStandard
from src.parsers.db_loader import hydrate_legs_from_catalog

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


class TemplateExistsError(FileExistsError):
    def __init__(self, name: str, path: Path):
        super().__init__(str(path))
        self.name = name
        self.path = path


class TemplateNameError(ValueError):
    pass


def default_templates_dir(data_root: Optional[Path] = None) -> Path:
    return (data_root or default_data_root()) / "leg_templates"


def sanitize_template_filename(name: str) -> str:
    text = _INVALID_CHARS.sub("_", (name or "").strip())
    return text.strip(" .")


def unique_test_names(legs: List[TestLeg]) -> List[str]:
    seen = set()
    out: List[str] = []
    for leg in legs or []:
        for node in leg.nodes or []:
            name = (node.test_name or "").strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


def node_for_template(node: TestNode) -> TestNode:
    """Keep card name and standard identity; drop library-sourced content."""
    standards = [
        TestStandard(
            standard_id=item.standard_id,
            chapter=item.chapter,
            test_name=item.test_name,
        )
        for item in (node.resolved_standards() or [])
    ]
    out = TestNode(test_name=node.test_name or "")
    out.apply_standards(standards)
    return out


def legs_for_template(legs: List[TestLeg]) -> List[TestLeg]:
    return [
        TestLeg(
            leg_id=leg.leg_id,
            leg_name=leg.leg_name,
            nodes=[node_for_template(node) for node in (leg.nodes or [])],
        )
        for leg in (legs or [])
    ]


@dataclass
class SavedLegTemplate:
    name: str
    json_path: Path
    saved_at: float
    leg_count: int
    test_count: int


def template_path_for(name: str, templates_dir: Optional[Path] = None) -> Path:
    filename = sanitize_template_filename(name)
    if not filename:
        raise TemplateNameError("模板名称不能为空")
    return (templates_dir or default_templates_dir()) / f"{filename}.json"


def save_leg_template(
    name: str,
    legs: List[TestLeg],
    templates_dir: Optional[Path] = None,
    overwrite: bool = False,
) -> Path:
    display_name = (name or "").strip()
    if not display_name:
        raise TemplateNameError("模板名称不能为空")
    dest_dir = templates_dir or default_templates_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = template_path_for(display_name, dest_dir)
    if path.exists() and not overwrite:
        raise TemplateExistsError(display_name, path)
    payload = {
        "name": display_name,
        "legs": [leg.model_dump() for leg in legs_for_template(legs)],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_leg_template(path: Path) -> Tuple[str, List[TestLeg]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    name = str(data.get("name") or Path(path).stem).strip()
    raw_legs = data.get("legs") or []
    legs = legs_for_template([TestLeg(**item) for item in raw_legs])
    return name, legs


def apply_leg_template(state: ProjectState, name: str, legs: List[TestLeg], catalog=None) -> None:
    """Replace legs and refresh template_pool. Never mutates candidate_pool.

    Identity-only legs are filled from the live standard catalog when provided.
    """
    stripped = legs_for_template(legs)
    if catalog is not None:
        hydrate_legs_from_catalog(stripped, catalog)
    state.legs = stripped
    state.template_pool = unique_test_names(state.legs)
    state.last_leg_template_name = (name or "").strip()


def list_leg_templates(templates_dir: Optional[Path] = None) -> List[SavedLegTemplate]:
    root = templates_dir or default_templates_dir()
    if not root.is_dir():
        return []
    found: List[SavedLegTemplate] = []
    for json_path in sorted(root.glob("*.json")):
        try:
            name, legs = load_leg_template(json_path)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        try:
            saved_at = json_path.stat().st_mtime
        except OSError:
            saved_at = 0.0
        found.append(
            SavedLegTemplate(
                name=name,
                json_path=json_path,
                saved_at=saved_at,
                leg_count=len(legs),
                test_count=sum(len(leg.nodes) for leg in legs),
            )
        )
    found.sort(key=lambda item: item.saved_at, reverse=True)
    return found
