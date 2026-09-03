from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_app_icon_files_exist():
    ico = ROOT / "assets" / "app.ico"
    png = ROOT / "assets" / "app.png"
    assert ico.is_file() and ico.stat().st_size > 0
    assert png.is_file() and png.stat().st_size > 0


def test_app_icon_path_prefers_ico():
    import sys

    from PySide6.QtWidgets import QApplication

    from src.ui.app_icon import app_icon_path, load_app_icon

    if QApplication.instance() is None:
        QApplication(sys.argv)

    path = app_icon_path()
    assert path == ROOT / "assets" / "app.ico"
    icon = load_app_icon()
    assert icon is not None
    assert not icon.isNull()


def test_ico_contains_desktop_sizes():
    from PIL import Image

    with Image.open(ROOT / "assets" / "app.ico") as img:
        sizes = set(img.ico.sizes()) if hasattr(img, "ico") else {img.size}
    assert (16, 16) in sizes
    assert (32, 32) in sizes
    assert (48, 48) in sizes


def test_update_rewrites_desktop_shortcut():
    text = (ROOT / "windows-deploy" / "update.bat").read_text(encoding="utf-8", errors="ignore")
    assert "WriteDesktopShortcut" in text


def test_shortcut_script_sets_icon_location():
    ps1 = (ROOT / "windows-deploy" / "_lib" / "create_shortcut.ps1").read_text(
        encoding="utf-8", errors="ignore"
    )
    assert "IconPath" in ps1
    assert "IconLocation" in ps1
    bat = (ROOT / "windows-deploy" / "_lib" / "common.bat").read_text(
        encoding="utf-8", errors="ignore"
    )
    assert "assets\\app.ico" in bat
    assert "-IconPath" in bat
