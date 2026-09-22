from pathlib import Path

from src.io.project_mirror import repo_root
from src.parsers.elp_plan import (
    caption_from_stem,
    elp_names_match,
    extract_plan_number_from_text,
    find_elp_plan_pdf,
    is_elp_plan_attachment,
    is_elp_plan_filename,
    lookup_work_mode,
    parse_elp_plan,
    resolve_elp_plan_pdf,
    tesseract_cmd,
)


EXAMPLE_PROJECT = repo_root() / "example" / "A2260745791101"
EXAMPLE_PDF = (
    EXAMPLE_PROJECT
    / "1.接样组"
    / "P166-6608707284-副仪表板开关组-ELP测试计划-20260713.pdf"
)


def test_elp_names_match_pin_space_and_conjunction():
    assert elp_names_match("PIN断路", "Pin 断路")
    assert elp_names_match("Pin断路和连接器断路", "PIN断路")
    assert elp_names_match("供给电压缓降和缓升", "缓降缓升")
    assert elp_names_match("清零重设行为", "清零重设")
    assert not elp_names_match("启动脉冲", "反极性")
    assert not elp_names_match("", "启动脉冲")


def test_caption_from_stem_strips_picture_index():
    assert caption_from_stem("图片10：校准图冷启动t6") == "校准图冷启动t6"
    assert caption_from_stem("图片 5: 试验布置") == "试验布置"
    assert caption_from_stem("试验后样件") == "试验后样件"


def test_extract_plan_number_from_cover_text():
    raw = "P166-ELP-TP (副仪表板开关组)-2026-0001"
    assert extract_plan_number_from_text(raw) == "P166-ELP-TP(副仪表板开关组)-2026-0001"
    plain = "ELP测试计划编号 L946-A1-ELP-TP-2026-0045"
    assert extract_plan_number_from_text(plain) == "L946-A1-ELP-TP-2026-0045"
    assert extract_plan_number_from_text("no plan here") == ""


def test_find_elp_plan_pdf_prefers_named_file(tmp_path: Path):
    sample = tmp_path / "1.接样组"
    sample.mkdir()
    (sample / "报价单-电性能.pdf").write_bytes(b"%PDF")
    target = sample / "P166-xxx-ELP测试计划-20260713.pdf"
    target.write_bytes(b"%PDF")
    (sample / "other.pdf").write_bytes(b"%PDF")
    assert find_elp_plan_pdf(tmp_path) == target
    assert find_elp_plan_pdf(None) is None
    assert is_elp_plan_filename(target.name)
    assert not is_elp_plan_filename("报价单-电性能.pdf")
    assert is_elp_plan_attachment(target)
    assert not is_elp_plan_attachment(sample / "报价单-电性能.pdf")


def test_resolve_elp_plan_pdf_falls_back_to_source(tmp_path: Path):
    local = tmp_path / "local"
    source = tmp_path / "source"
    (local / "1.接样组").mkdir(parents=True)
    (source / "1.接样组").mkdir(parents=True)
    (source / "1.接样组" / "报价单-电性能.pdf").write_bytes(b"%PDF")
    remote_plan = source / "1.接样组" / "P166-ELP测试计划.pdf"
    remote_plan.write_bytes(b"%PDF-source")
    assert resolve_elp_plan_pdf(local, source) == remote_plan

    local_plan = local / "1.接样组" / "local-ELP测试计划.pdf"
    local_plan.write_bytes(b"%PDF-local")
    assert resolve_elp_plan_pdf(local, source) == local_plan
    assert resolve_elp_plan_pdf(None, source) == remote_plan
    assert resolve_elp_plan_pdf(None, None) is None


def test_parse_example_elp_plan_without_ocr():
    if not EXAMPLE_PDF.is_file():
        return
    plan = parse_elp_plan(EXAMPLE_PDF, ocr_cover=False)
    assert plan.product_name == "副仪表板开关组"
    assert plan.vehicle_code == "P166"
    assert plan.part_no == "6608707284"
    assert plan.hw_version == "V1.0"
    assert plan.sw_version == "V1.0"
    assert plan.basic_ticks["电子电器组件种类"] == ["A"]
    assert "连续型" in plan.basic_ticks["工作类型"]
    assert plan.extra_info["DUT最大峰值电流消耗"] == "≤210mA"
    assert lookup_work_mode(plan.test_work_modes, "启动脉冲")
    assert lookup_work_mode(plan.test_work_modes, "Pin 断路")
    assert len(plan.monitor_rows) >= 2
    assert plan.monitor_rows[0][1]
    assert any(name.startswith("功能状态A") for name, _desc in plan.function_states)
    assert plan.basic_info_rows
    assert plan.basic_info_rows[0][0].startswith("电子电器组件种类")
    assert any(row and row[0].startswith("mode 1.1") for row in plan.function_class_rows)
    assert set(plan.chapter6_images) >= {
        "basic",
        "function_class",
        "work_modes",
        "monitor",
        "states",
    }
    for blob in plan.chapter6_images.values():
        assert blob.startswith(b"\x89PNG")
    from PIL import Image
    import io

    with Image.open(io.BytesIO(plan.chapter6_images["work_modes"])) as im:
        # 300 dpi, table plus the 备注 block under it.
        assert im.size[1] > 780


def test_find_elp_plan_in_example_project():
    if not EXAMPLE_PROJECT.is_dir():
        return
    found = find_elp_plan_pdf(EXAMPLE_PROJECT)
    assert found is not None
    assert found.suffix.lower() == ".pdf"
    assert "ELP" in found.name.upper() or "测试计划" in found.name


def _left_rule_pixels(blob: bytes) -> int:
    import io

    from PIL import Image

    with Image.open(io.BytesIO(blob)) as im:
        gray = im.convert("L")
        width, height = gray.size
        pixels = gray.load()
        dark = 0
        for y in range(height // 5, 4 * height // 5, 2):
            for x in range(min(28, width)):
                if pixels[x, y] < 80:
                    dark += 1
        return dark


def test_text_cover_plan_number_without_ocr():
    sample = repo_root() / "data" / "A2260774870101" / "1.接样组"
    if not sample.is_dir():
        return
    matches = [
        path
        for path in sample.glob("*.pdf")
        if "ELP" in path.name.upper() and "报价" not in path.name
    ]
    if not matches:
        return
    plan = parse_elp_plan(matches[0], ocr_cover=False)
    assert plan.plan_no == "L946-A1-ELP-TP-2026-0045"
    assert set(plan.chapter6_images) >= {
        "basic",
        "function_class",
        "work_modes",
        "monitor",
        "states",
    }
    # Outer left rule must be inside the crop (6.4 / 6.5 used to start past it).
    for key in ("monitor", "states"):
        assert _left_rule_pixels(plan.chapter6_images[key]) > 30


def test_ocr_example_cover_fills_plan_number():
    if not EXAMPLE_PDF.is_file() or tesseract_cmd() is None:
        return
    plan = parse_elp_plan(EXAMPLE_PDF, ocr_cover=True)
    assert plan.plan_no == "P166-ELP-TP(副仪表板开关组)-2026-0001"
