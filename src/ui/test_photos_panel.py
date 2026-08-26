"""试验照片 drawer: album rows, drag-in copy, thumbnails."""

from pathlib import Path
import tempfile

from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QSize, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea,
    QDialog, QRadioButton, QLineEdit, QButtonGroup, QMessageBox, QInputDialog,
    QSizePolicy, QLayout,
)

from src.ui.theme import BG_INPUT, CYAN
from src.ui.window_focus import force_window_foreground

from src.io.test_photos import (
    PhotoError,
    collect_drop_images,
    copy_into_album,
    copy_into_album_keep_names,
    create_album,
    create_template_albums,
    delete_album,
    delete_photo,
    is_usable_test_name,
    list_albums,
    list_photos,
    rename_album,
    rename_all_in_album,
    rename_photo,
    album_dir,
)

# Sentinel from RenamePhotosDialog / _ask_prefix: keep source basenames on import.
KEEP_ORIGINAL = object()


THUMB = 72
NAME_H = 18
THUMB_GAP = 6
VISIBLE_ROWS = 2
THUMB_CARD_H = THUMB + 10 + NAME_H
GALLERY_H = VISIBLE_ROWS * THUMB_CARD_H + (VISIBLE_ROWS - 1) * THUMB_GAP
_RADIO_QSS = None


def _radio_indicator_qss():
    global _RADIO_QSS
    if _RADIO_QSS is not None:
        return _RADIO_QSS
    folder = Path(tempfile.gettempdir()) / "report-creator-radio"
    folder.mkdir(exist_ok=True)
    off_path = folder / "radio-off.png"
    on_path = folder / "radio-on.png"
    _paint_radio_pixmap(False).save(str(off_path))
    _paint_radio_pixmap(True).save(str(on_path))
    off = off_path.resolve().as_posix()
    on = on_path.resolve().as_posix()
    _RADIO_QSS = f"""
QRadioButton#photoRenameRadio::indicator {{
    width: 18px;
    height: 18px;
    border: none;
    image: url("{off}");
}}
QRadioButton#photoRenameRadio::indicator:checked {{
    image: url("{on}");
}}
QRadioButton#photoRenameRadio::indicator:disabled {{
    image: url("{off}");
}}
"""
    return _RADIO_QSS


def _paint_radio_pixmap(checked):
    pix = QPixmap(36, 36)
    pix.fill(Qt.transparent)
    pix.setDevicePixelRatio(2)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(2, 2, 14, 14)
    painter.setPen(QPen(QColor(CYAN), 1.8))
    painter.setBrush(QColor(BG_INPUT))
    painter.drawRoundedRect(rect, 2.5, 2.5)
    if checked:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(CYAN))
        painter.drawEllipse(QRectF(0, 0, 7, 7).translated(5.5, 5.5))
    painter.end()
    return pix


class FlowLayout(QLayout):
    """Left-to-right wrap; used so the gallery can scroll vertically."""

    def __init__(self, parent=None, spacing=THUMB_GAP):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0
        space = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + space
            if line_height > 0 and next_x - space > rect.right() + 1:
                x = rect.x()
                y = y + line_height + space
                next_x = x + hint.width() + space
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() if self._items else 0


class ThumbGallery(QScrollArea):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_host()

    def _fit_host(self):
        host = self.widget()
        if host is None:
            return
        width = max(self.viewport().width(), 1)
        layout = host.layout()
        height = layout.heightForWidth(width) if layout is not None else host.sizeHint().height()
        host.setFixedWidth(width)
        host.setMinimumHeight(max(height, 1))
        host.resize(width, max(height, 1))

class FolderChip(QWidget):
    """Folder-shaped label; double-click to rename."""

    doubleClicked = Signal()

    def __init__(self, name="", parent=None):
        super().__init__(parent)
        self._name = name or ""
        self.setObjectName("photoFolderChip")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("双击改名")
        self.setFixedSize(92, 64)

    def setText(self, name):
        self._name = name or ""
        self.update()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tab_h = 11
        tab_w = int(w * 0.42)
        path = QPainterPath()
        path.moveTo(2, tab_h)
        path.lineTo(2, 5)
        path.quadTo(2, 2, 5, 2)
        path.lineTo(tab_w - 3, 2)
        path.quadTo(tab_w + 2, 2, tab_w + 6, tab_h)
        path.lineTo(w - 5, tab_h)
        path.quadTo(w - 2, tab_h, w - 2, tab_h + 3)
        path.lineTo(w - 2, h - 5)
        path.quadTo(w - 2, h - 2, w - 5, h - 2)
        path.lineTo(5, h - 2)
        path.quadTo(2, h - 2, 2, h - 5)
        path.closeSubpath()
        painter.setPen(QPen(QColor(CYAN), 1.6))
        painter.setBrush(QColor("#12181F"))
        painter.drawPath(path)
        painter.setPen(QColor(CYAN))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        text_rect = self.rect().adjusted(6, tab_h + 2, -6, -6)
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, self._name)


class RenamePhotosDialog(QDialog):
    def __init__(
        self,
        folder_name,
        project_id,
        parent=None,
        title="重命名照片",
        allow_keep_original=False,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._folder_name = folder_name or "照片"
        self._project_id = (project_id or "").strip()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("选择重命名方式："))

        self.group = QButtonGroup(self)
        self.radio_folder = QRadioButton(f"按文件夹名（{self._folder_name}-001）")
        self.radio_project = QRadioButton(
            f"按项目号（{self._project_id}-001）" if self._project_id else "按项目号（当前没有项目号）"
        )
        self.radio_custom = QRadioButton("自定义前缀")
        self.radio_keep = QRadioButton("保持原图片名") if allow_keep_original else None
        self.radio_folder.setChecked(True)
        self.radio_project.setEnabled(bool(self._project_id))
        radio_qss = _radio_indicator_qss()

        def _add_radio(radio, idx):
            radio.setObjectName("photoRenameRadio")
            radio.setStyleSheet(radio_qss)
            self.group.addButton(radio, idx)
            layout.addWidget(radio)

        _add_radio(self.radio_folder, 0)
        _add_radio(self.radio_project, 1)
        _add_radio(self.radio_custom, 2)

        self.txt_custom = QLineEdit()
        self.txt_custom.setPlaceholderText("例如：样品")
        self.txt_custom.setEnabled(False)
        self.radio_custom.toggled.connect(self.txt_custom.setEnabled)
        layout.addWidget(self.txt_custom)

        if self.radio_keep is not None:
            _add_radio(self.radio_keep, 3)

        buttons = QHBoxLayout()
        buttons.addStretch()
        ok = QPushButton("确定")
        cancel = QPushButton("取消")
        ok.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def showEvent(self, event):
        super().showEvent(event)
        # After Finder/Explorer drag-drop the dialog can appear without becoming
        # the OS foreground window (taskbar/Dock flash only). Steal focus once shown.
        QTimer.singleShot(0, lambda: force_window_foreground(self))

    def _accept(self):
        try:
            self.choice()
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self.accept()

    def choice(self):
        """Return KEEP_ORIGINAL or a prefix string."""
        if self.radio_keep is not None and self.radio_keep.isChecked():
            return KEEP_ORIGINAL
        if self.radio_folder.isChecked():
            return self._folder_name
        if self.radio_project.isChecked():
            if not self._project_id:
                raise PhotoError("当前没有项目号，请先加载项目")
            return self._project_id
        text = self.txt_custom.text().strip()
        if not text:
            raise PhotoError("请输入自定义前缀")
        return text

    def prefix(self):
        """Backward-compatible: prefix string only (not keep-original)."""
        result = self.choice()
        if result is KEEP_ORIGINAL:
            raise PhotoError("当前选择是保持原图片名")
        return result


class PhotoThumb(QFrame):
    removed = Signal()
    renamed = Signal()

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self._popup = None
        self.setObjectName("photoThumb")
        self.setFixedSize(THUMB + 18, THUMB + 10 + NAME_H)
        self.setToolTip("单击放大，双击重命名")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(2)

        self.lbl = QLabel()
        self.lbl.setAlignment(Qt.AlignCenter)
        self.lbl.setCursor(Qt.PointingHandCursor)
        pix = QPixmap(str(self.path))
        if not pix.isNull():
            self.lbl.setPixmap(
                pix.scaled(THUMB, THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self.lbl.mousePressEvent = self._on_press
        self.lbl.mouseDoubleClickEvent = self._on_double_click
        layout.addWidget(self.lbl)

        self.lbl_name = QLabel()
        self.lbl_name.setObjectName("photoThumbName")
        self.lbl_name.setAlignment(Qt.AlignCenter)
        self.lbl_name.setToolTip(self.path.name + "（双击重命名）")
        self.lbl_name.setCursor(Qt.PointingHandCursor)
        self.lbl_name.mousePressEvent = self._on_press
        self.lbl_name.mouseDoubleClickEvent = self._on_double_click
        layout.addWidget(self.lbl_name)

        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(280)
        self._click_timer.timeout.connect(self._show_popup)

        btn = QPushButton("✕")
        btn.setObjectName("photoThumbDelete")
        btn.setFixedSize(18, 18)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("从本地镜像中删除")
        btn.clicked.connect(self._delete)
        btn.setParent(self)
        btn.move(self.width() - 20, 2)
        btn.raise_()
        self._elide_name()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        btn = self.findChild(QPushButton, "photoThumbDelete")
        if btn is not None:
            btn.move(self.width() - 20, 2)
        self._elide_name()

    def _elide_name(self):
        if not hasattr(self, "lbl_name"):
            return
        width = max(self.lbl_name.width(), self.width() - 8, 1)
        self.lbl_name.setText(
            self.lbl_name.fontMetrics().elidedText(self.path.name, Qt.ElideMiddle, width)
        )

    def _on_press(self, event):
        if event.button() != Qt.LeftButton:
            return
        self._click_timer.start()

    def _on_double_click(self, event):
        if event.button() != Qt.LeftButton:
            return
        self._click_timer.stop()
        self._rename()
        event.accept()

    def _show_popup(self):
        from src.ui.test_detail_dialog import StdImagePopup

        pix = QPixmap(str(self.path))
        if pix.isNull():
            return
        host = self.window()
        max_w = max(int((host.width() if host else 800) * 0.75), 240)
        max_h = max(int((host.height() if host else 600) * 0.75), 180)
        if pix.width() > max_w or pix.height() > max_h:
            pix = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        popup = StdImagePopup(pix, host)
        self._popup = popup
        if host is not None:
            popup.move(host.mapToGlobal(host.rect().center()) - popup.rect().center())
        popup.show()
        popup.raise_()

    def _rename(self):
        text, ok = QInputDialog.getText(
            self, "重命名照片", "新的文件名：", text=self.path.name
        )
        if not ok:
            return
        try:
            self.path = rename_photo(self.path, text)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self.lbl_name.setToolTip(self.path.name + "（双击重命名）")
        self._elide_name()
        self.renamed.emit()

    def _delete(self):
        self._click_timer.stop()
        delete_photo(self.path)
        self.removed.emit()


class PhotoAlbumRow(QFrame):
    changed = Signal()

    def __init__(self, project_root: Path, test_name: str, album_name: str, project_id: str, parent=None):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.test_name = test_name
        self.album_name = album_name
        self.project_id = project_id
        self.setObjectName("photoAlbumRow")
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)

        folder_wrap = QWidget()
        folder_wrap.setFixedSize(102, 74)
        self.chip = FolderChip(album_name, folder_wrap)
        self.chip.move(0, 8)
        self.chip.doubleClicked.connect(self._rename_folder)
        self.btn_delete = QPushButton("✕", folder_wrap)
        self.btn_delete.setObjectName("photoThumbDelete")
        self.btn_delete.setFixedSize(18, 18)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setToolTip("删除文件夹")
        self.btn_delete.move(82, 0)
        self.btn_delete.clicked.connect(self._delete_folder)
        self.btn_delete.raise_()
        left.addWidget(folder_wrap, 0, Qt.AlignHCenter)

        self.btn_rename_all = QPushButton("所有照片重命名")
        self.btn_rename_all.setObjectName("photoRenameAllLink")
        self.btn_rename_all.setCursor(Qt.PointingHandCursor)
        self.btn_rename_all.setFixedWidth(102)
        self.btn_rename_all.clicked.connect(self._rename_all)
        left.addWidget(self.btn_rename_all, 0, Qt.AlignHCenter)
        left.addStretch(1)
        root.addLayout(left, 0)
        root.setAlignment(Qt.AlignTop)

        self.thumb_host = QWidget()
        self.thumb_layout = FlowLayout(self.thumb_host, spacing=THUMB_GAP)
        self.scroll = ThumbGallery()
        self.scroll.setWidgetResizable(False)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setFixedHeight(GALLERY_H)
        self.scroll.setWidget(self.thumb_host)
        root.addWidget(self.scroll, stretch=1)
        self.reload()

    def folder(self) -> Path:
        return album_dir(self.project_root, self.test_name, self.album_name)

    def reload(self):
        while self.thumb_layout.count():
            item = self.thumb_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        photos = list_photos(self.project_root, self.test_name, self.album_name)
        for path in photos:
            thumb = PhotoThumb(path, self.thumb_host)
            thumb.removed.connect(self._on_thumb_removed)
            thumb.renamed.connect(self._on_thumb_renamed)
            self.thumb_layout.addWidget(thumb)
        self.chip.setText(self.album_name)
        QTimer.singleShot(0, self.scroll._fit_host)

    def _on_thumb_removed(self):
        self.reload()
        self.changed.emit()

    def _on_thumb_renamed(self):
        self.reload()
        self.changed.emit()

    def _ask_prefix(self, title, allow_keep_original=False):
        dlg = RenamePhotosDialog(
            self.album_name,
            self.project_id,
            self,
            title=title,
            allow_keep_original=allow_keep_original,
        )
        if dlg.exec() != QDialog.Accepted:
            return None
        return dlg.choice()

    def _import_paths(self, paths):
        images, skipped = collect_drop_images(paths)
        if not images:
            extra = f"\n已跳过：{', '.join(skipped[:6])}" if skipped else ""
            QMessageBox.information(self, "提示", "没有可导入的 jpg / jpeg / png。" + extra)
            return
        choice = self._ask_prefix("重命名照片", allow_keep_original=True)
        if choice is None:
            return
        if choice is KEEP_ORIGINAL:
            copy_into_album_keep_names(self.folder(), images)
        else:
            copy_into_album(self.folder(), images, choice)
        self.reload()
        self.changed.emit()

    def _rename_all(self):
        photos = list_photos(self.project_root, self.test_name, self.album_name)
        if not photos:
            QMessageBox.information(self, "提示", "这个文件夹里还没有照片。")
            return
        prefix = self._ask_prefix("所有照片重命名")
        if not prefix:
            return
        try:
            rename_all_in_album(self.folder(), prefix)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self.reload()
        self.changed.emit()

    def _rename_folder(self):
        text, ok = QInputDialog.getText(self, "改名", "新的文件夹名称：", text=self.album_name)
        if not ok:
            return
        try:
            rename_album(self.project_root, self.test_name, self.album_name, text)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self.album_name = text.strip()
        self.reload()
        self.changed.emit()

    def _delete_folder(self):
        answer = QMessageBox.question(
            self,
            "删除照片文件夹",
            "是否删除文件夹？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        delete_album(self.project_root, self.test_name, self.album_name)
        self.changed.emit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        paths = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
        event.setDropAction(Qt.CopyAction)
        event.accept()
        if paths:
            # Defer until the file-manager finishes the drop gesture, otherwise
            # the rename dialog often cannot take foreground focus.
            QTimer.singleShot(0, lambda: self._import_paths(paths))


class TestPhotosPanel(QWidget):
    changed = Signal()

    def __init__(self, project_root, test_name, project_id, parent=None):
        super().__init__(parent)
        self.project_root = Path(project_root) if project_root else None
        self.test_name = test_name or ""
        self.project_id = project_id or ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setObjectName("dimLabel")
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        toolbar = QHBoxLayout()
        self.btn_template = QPushButton("模版新建")
        self.btn_template.setToolTip("一次开出：试验前、试验中、试验后、数据（已有的跳过）")
        self.btn_custom = QPushButton("自定义新建")
        self.btn_template.clicked.connect(self._add_template)
        self.btn_custom.clicked.connect(self._add_custom)
        toolbar.addWidget(self.btn_template)
        toolbar.addWidget(self.btn_custom)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        layout.addWidget(self.rows_host)

        self.reload()

    def counts(self):
        if self.project_root is None or not is_usable_test_name(self.test_name):
            return 0, 0
        albums = list_albums(self.project_root, self.test_name)
        photos = 0
        for name in albums:
            photos += len(list_photos(self.project_root, self.test_name, name))
        return len(albums), photos

    def _ready(self):
        if self.project_root is None or not self.project_root.is_dir():
            QMessageBox.warning(self, "提示", "本地镜像尚未就绪。")
            return False
        if not is_usable_test_name(self.test_name):
            QMessageBox.warning(self, "提示", "请先在主界面选择试验名称。")
            return False
        return True

    def reload(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        usable = is_usable_test_name(self.test_name)
        mirrored = self.project_root is not None and self.project_root.is_dir()
        enabled = usable and mirrored
        self.btn_template.setEnabled(enabled)
        self.btn_custom.setEnabled(enabled)

        if not usable:
            self.lbl_hint.setText("请先在主界面选择试验名称，再管理试验照片。")
            self.lbl_hint.show()
            return
        if not mirrored:
            self.lbl_hint.setText("本地镜像尚未完成，暂时不能写入试验照片。")
            self.lbl_hint.show()
            return

        albums = list_albums(self.project_root, self.test_name)
        if albums:
            self.lbl_hint.setText("把图片或一层文件夹拖到某一行，即拷贝到本地镜像并重命名。")
        else:
            self.lbl_hint.setText("还没有照片文件夹。可用「模版新建」一次开出试验前 / 中 / 后 / 数据。")
        self.lbl_hint.show()
        for name in albums:
            row = PhotoAlbumRow(self.project_root, self.test_name, name, self.project_id, self.rows_host)
            row.changed.connect(self._on_row_changed)
            self.rows_layout.addWidget(row)

    def _on_row_changed(self):
        self.reload()
        self.changed.emit()

    def _add_template(self):
        if not self._ready():
            return
        try:
            created = create_template_albums(self.project_root, self.test_name)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        if not created and list_albums(self.project_root, self.test_name):
            QMessageBox.information(self, "提示", "模版四个文件夹都已存在。")
        self.reload()
        self.changed.emit()

    def _add_custom(self):
        if not self._ready():
            return
        text, ok = QInputDialog.getText(self, "自定义新建", "文件夹名称：")
        if not ok:
            return
        try:
            create_album(self.project_root, self.test_name, text)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self.reload()
        self.changed.emit()
