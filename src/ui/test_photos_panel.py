"""试验照片 drawer: album rows, drag-in copy, thumbnails."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
from typing import List, Optional

from PySide6.QtCore import Qt, QByteArray, QMimeData, QPoint, QRect, QRectF, QSize, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QDialog, QRadioButton, QLineEdit, QButtonGroup, QMessageBox, QInputDialog,
    QSizePolicy, QListView, QListWidgetItem, QStyledItemDelegate,
)
from src.ui.scroll_contain import ContainedListWidget

from src.ui.theme import BG, BG_INPUT, BG_PANEL, BORDER, CYAN, TEXT_DIM
from src.ui.window_focus import force_window_foreground

from src.io.project_assets import (
    MergedPhoto,
    download_photo_to_album,
    list_merged_albums,
    list_merged_photos,
    list_merged_spare_photos,
    move_photo_to_spare,
    original_view_path,
    preview_path_for_photo,
    rename_all_merged_in_album,
    rename_merged_photo,
    renumber_merged_photos,
    resolve_photo_path,
    spare_dir,
    thumbnail_for_photo,
)
from src.io.test_photos import (
    PhotoError,
    SPARE_ALBUM_NAME,
    collect_drop_images,
    copy_into_album,
    copy_into_album_keep_names,
    create_album,
    create_template_albums,
    delete_album,
    infer_numbered_prefix,
    is_usable_test_name,
    remap_album_order,
    rename_album,
    album_dir,
)
from src.ui.gantt_utils import find_leg_for_node
from src.models.project_state import DUPLICATE_TEST_NAME_MESSAGE
from src.ui.photo_inbox_dialog import PhotoInboxDialog

# Sentinel from RenamePhotosDialog / _ask_prefix: keep source basenames on import.
KEEP_ORIGINAL = object()
ALBUM_ORDER_MIME = "application/x-reach-photo-album"


def warn_duplicate_test_names(parent) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("提示")
    box.setText(DUPLICATE_TEST_NAME_MESSAGE)
    box.addButton("确认", QMessageBox.AcceptRole)
    box.exec()


THUMB = 72
NAME_H = 18
THUMB_GAP = 6
VISIBLE_ROWS = 2
THUMB_CARD_W = THUMB + 18
THUMB_CARD_H = THUMB + 10 + NAME_H
GALLERY_H = VISIBLE_ROWS * THUMB_CARD_H + (VISIBLE_ROWS - 1) * THUMB_GAP
PHOTO_REL_ROLE = Qt.UserRole
PHOTO_CLOUD_ROLE = Qt.UserRole + 1
PHOTO_PATH_ROLE = Qt.UserRole + 2
_RADIO_QSS = None
_CLOUD_PIX = None


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


def _cloud_pixmap():
    global _CLOUD_PIX
    if _CLOUD_PIX is None:
        _CLOUD_PIX = _paint_cloud_pixmap()
    return _CLOUD_PIX


def _delete_btn_rect(item_rect: QRect) -> QRect:
    return QRect(item_rect.right() - 20, item_rect.top() + 2, 18, 18)


def _cloud_btn_rect(item_rect: QRect) -> QRect:
    return QRect(item_rect.left() + 4, item_rect.top() + 2, 18, 18)


def _download_btn_rect(item_rect: QRect) -> QRect:
    return QRect(item_rect.left() + 4, item_rect.top() + 22, 18, 18)


class PhotoThumbDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        cloud = bool(index.data(PHOTO_CLOUD_ROLE))
        spare = bool(getattr(self.parent(), "_in_spare", False))
        if cloud:
            badge = _cloud_pixmap()
            box = _cloud_btn_rect(rect)
            painter.drawPixmap(box.topLeft(), badge.scaled(box.size()))
            if not spare:
                painter.setPen(QPen(QColor(CYAN), 1))
                painter.setBrush(QColor(BG_PANEL))
                dl = _download_btn_rect(rect)
                painter.drawRoundedRect(dl, 9, 9)
                painter.setPen(QColor(CYAN))
                painter.drawText(dl, Qt.AlignCenter, "↓")
        if not spare:
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.setBrush(QColor(BG))
            box = _delete_btn_rect(rect)
            painter.drawRoundedRect(box, 9, 9)
            painter.setPen(QColor(TEXT_DIM))
            painter.drawText(box, Qt.AlignCenter, "✕")
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(THUMB_CARD_W, THUMB_CARD_H)


class PhotoThumbList(ContainedListWidget):
    def __init__(self, row, in_spare=False, parent=None):
        super().__init__(parent)
        self._row = row
        self._in_spare = bool(in_spare)
        self._press_hit = None
        self._press_global: Optional[QPoint] = None
        self._dragging = False
        self._dragging_rel = ""
        self._visual_order: Optional[List[str]] = None
        self._order_at_press: Optional[List[str]] = None
        self._ignore_click = False
        self.setObjectName("photoThumbList")
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setDragEnabled(False)
        self.setAcceptDrops(not self._in_spare)
        self.viewport().setAcceptDrops(not self._in_spare)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(
            QAbstractItemView.DropOnly if not self._in_spare else QAbstractItemView.NoDragDrop
        )
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setIconSize(QSize(THUMB, THUMB))
        self.setGridSize(QSize(THUMB_CARD_W + THUMB_GAP, THUMB_CARD_H + THUMB_GAP))
        self.setSpacing(THUMB_GAP)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(GALLERY_H)
        self.setItemDelegate(PhotoThumbDelegate(self))
        if not self._in_spare:
            self.setCursor(Qt.OpenHandCursor)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(280)
        self._click_timer.timeout.connect(self._emit_preview)
        self._click_rel = ""
        self.itemClicked.connect(self._on_item_clicked)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)

    def ordered_rels(self) -> List[str]:
        out = []
        for i in range(self.count()):
            item = self.item(i)
            if item is not None:
                rel = item.data(PHOTO_REL_ROLE)
                if rel:
                    out.append(rel)
        return out

    def add_photo(self, photo: MergedPhoto, local_root: Path) -> None:
        pix = QPixmap()
        display = Path(photo.read_path)
        try:
            display = thumbnail_for_photo(
                local_root, photo.relative_path, photo.read_path, size=THUMB * 2
            )
        except Exception:
            pass
        loaded = QPixmap(str(display))
        if not loaded.isNull():
            pix = loaded.scaled(THUMB, THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        item = QListWidgetItem(QIcon(pix), Path(photo.read_path).name)
        item.setData(PHOTO_REL_ROLE, photo.relative_path)
        item.setData(PHOTO_CLOUD_ROLE, bool(photo.is_cloud_only))
        item.setData(PHOTO_PATH_ROLE, str(photo.read_path))
        item.setSizeHint(QSize(THUMB_CARD_W, THUMB_CARD_H))
        item.setToolTip(Path(photo.read_path).name)
        self.addItem(item)

    def supportedDropActions(self):
        if self._in_spare:
            return Qt.IgnoreAction
        return Qt.CopyAction | Qt.MoveAction

    def _viewport_pos(self, event) -> QPoint:
        return self.viewport().mapFromGlobal(event.globalPosition().toPoint())

    def _item_index_for_rel(self, rel: str) -> Optional[int]:
        if not rel:
            return None
        for i in range(self.count()):
            item = self.item(i)
            if item is not None and item.data(PHOTO_REL_ROLE) == rel:
                return i
        return None

    def _dest_index_at(self, pos: QPoint) -> Optional[int]:
        order = self._visual_order
        rel = self._dragging_rel
        if not order or rel not in order:
            return None
        old = order.index(rel)
        hit = self.itemAt(pos)
        if hit is not None:
            hit_rel = hit.data(PHOTO_REL_ROLE) or ""
            if hit_rel == rel:
                return old
            if hit_rel in order:
                return order.index(hit_rel)
        if not self.viewport().rect().contains(pos):
            return old
        rects = []
        for i in range(self.count()):
            item = self.item(i)
            if item is not None:
                rects.append(self.visualItemRect(item))
        insert_at = insert_index_for_rects(rects, pos)
        moved = move_list_item(order, old, insert_at)
        return moved.index(rel) if rel in moved else old

    def _move_item(self, old: int, dest: int) -> None:
        if old == dest or old < 0 or dest < 0:
            return
        if old >= self.count() or dest >= self.count():
            return
        self.blockSignals(True)
        try:
            item = self.takeItem(old)
            if item is None:
                return
            self.insertItem(dest, item)
            self.setCurrentItem(item)
            self.doItemsLayout()
        finally:
            self.blockSignals(False)

    def _nudge_order(self, pos: QPoint) -> None:
        order = self._visual_order
        rel = self._dragging_rel
        dest = self._dest_index_at(pos)
        if order is None or rel not in order or dest is None:
            return
        old = order.index(rel)
        if dest == old:
            return
        dest = max(0, min(dest, len(order) - 1))
        if dest == old:
            return
        order.pop(old)
        order.insert(dest, rel)
        widget_old = self._item_index_for_rel(rel)
        if widget_old is not None:
            self._move_item(widget_old, dest)

    def _begin_reorder(self, rel: str) -> None:
        self._click_timer.stop()
        self._click_rel = ""
        self._dragging = True
        self._dragging_rel = rel
        if self._visual_order is None:
            self._visual_order = self.ordered_rels()
        if self._order_at_press is None:
            self._order_at_press = list(self._visual_order)
        self.setCursor(Qt.ClosedHandCursor)

    def _end_reorder(self) -> None:
        order = list(self._visual_order or [])
        origin = self._order_at_press
        self._dragging = False
        self._dragging_rel = ""
        self._press_global = None
        self._visual_order = None
        self._order_at_press = None
        try:
            self.setCursor(Qt.OpenHandCursor if not self._in_spare else Qt.ArrowCursor)
        except RuntimeError:
            pass
        if origin is not None and order and order != origin:
            self._row._write_photo_order(order)

    def mousePressEvent(self, event):
        self._press_hit = None
        self._press_global = None
        self._click_timer.stop()
        if event.button() == Qt.LeftButton:
            pos = self._viewport_pos(event)
            item = self.itemAt(pos)
            if item is not None and not self._in_spare:
                rect = self.visualItemRect(item)
                if _delete_btn_rect(rect).contains(pos):
                    self._press_hit = ("delete", item.data(PHOTO_REL_ROLE))
                    event.accept()
                    return
                if item.data(PHOTO_CLOUD_ROLE) and _download_btn_rect(rect).contains(pos):
                    self._press_hit = ("download", item.data(PHOTO_REL_ROLE))
                    event.accept()
                    return
                rel = item.data(PHOTO_REL_ROLE) or ""
                self._press_global = event.globalPosition().toPoint()
                self._dragging_rel = rel
                self._visual_order = self.ordered_rels()
                self._order_at_press = list(self._visual_order)
                self.blockSignals(True)
                try:
                    self.setCurrentItem(item)
                finally:
                    self.blockSignals(False)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging or (
            not self._in_spare
            and self._press_global is not None
            and (event.buttons() & Qt.LeftButton)
            and self._dragging_rel
        ):
            if not self._dragging:
                delta = event.globalPosition().toPoint() - self._press_global
                if delta.manhattanLength() < QApplication.startDragDistance():
                    event.accept()
                    return
                self._begin_reorder(self._dragging_rel)
            view_pos = self._viewport_pos(event)
            if self.viewport().rect().contains(view_pos):
                self._nudge_order(view_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        if self._ignore_click:
            self._ignore_click = False
            self._press_hit = None
            self._press_global = None
            self._dragging_rel = ""
            self._visual_order = None
            self._order_at_press = None
            event.accept()
            return
        if self._dragging:
            self._end_reorder()
            event.accept()
            return
        hit = self._press_hit
        pressed_rel = self._dragging_rel if self._press_global is not None else ""
        self._press_hit = None
        self._press_global = None
        self._dragging_rel = ""
        self._visual_order = None
        self._order_at_press = None
        if hit is not None:
            kind, rel = hit
            item = self.itemAt(self._viewport_pos(event))
            if item is not None and item.data(PHOTO_REL_ROLE) == rel:
                if kind == "delete":
                    self._row._delete_photo(rel)
                elif kind == "download":
                    self._row._download_photo(rel)
            event.accept()
            return
        if pressed_rel:
            self._click_rel = pressed_rel
            self._click_timer.start()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and not self._in_spare:
            item = self.itemAt(self._viewport_pos(event))
            if item is not None:
                self._ignore_click = True
                self._on_item_double_clicked(item)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _on_item_clicked(self, item):
        if self._press_hit is not None or self._dragging:
            return
        self._click_rel = item.data(PHOTO_REL_ROLE) or ""
        if self._click_rel:
            self._click_timer.start()

    def _on_item_double_clicked(self, item):
        self._click_timer.stop()
        rel = item.data(PHOTO_REL_ROLE) or ""
        if not rel:
            return
        if self._in_spare:
            if item.data(PHOTO_CLOUD_ROLE):
                self._row._show_original(rel)
            else:
                self._row._show_preview(rel)
            return
        self._row._rename_photo(rel)

    def _emit_preview(self):
        rel = self._click_rel
        self._click_rel = ""
        if rel:
            self._row._show_preview(rel)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if self._in_spare:
            event.ignore()
            return
        if self._row._accepts_album_reorder(event.mimeData()):
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if self._in_spare:
            event.ignore()
            return
        if self._row._accepts_album_reorder(event.mimeData()):
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        if self._in_spare:
            event.ignore()
            return
        if self._row._accepts_album_reorder(event.mimeData()):
            self._row.dropEvent(event)
            return
        urls = event.mimeData().urls()
        paths = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
        event.setDropAction(Qt.CopyAction)
        event.accept()
        if paths:
            QTimer.singleShot(0, lambda: self._row._import_paths(paths))


def album_name_from_mime(mime: QMimeData) -> str:
    raw = mime.data(ALBUM_ORDER_MIME)
    if raw:
        return bytes(raw).decode("utf-8").strip()
    return ""


def insert_index_for_album_y(host: QWidget, row_widgets: list, y: int) -> int:
    """Return list index to insert before, based on Y in host coordinates."""
    if not row_widgets:
        return 0
    for i, row in enumerate(row_widgets):
        top = row.mapTo(host, QPoint(0, 0)).y()
        center = top + row.height() // 2
        if y < center:
            return i
    return len(row_widgets)


def insert_index_for_rects(rects: list, pos: QPoint) -> int:
    """Insert-before index for a wrapped left-to-right flow of *rects*."""
    if not rects:
        return 0
    for i, geom in enumerate(rects):
        if pos.y() < geom.top() or (
            geom.top() <= pos.y() <= geom.bottom() and pos.x() < geom.center().x()
        ):
            return i
    return len(rects)


def move_list_item(items: list, old: int, insert_at: int) -> list:
    """Move *items[old]* so it lands at gap *insert_at* in the original list."""
    if not items or old < 0 or old >= len(items):
        return list(items)
    out = list(items)
    item = out.pop(old)
    dest = insert_at if insert_at <= old else insert_at - 1
    dest = max(0, min(dest, len(out)))
    out.insert(dest, item)
    return out


class FolderChip(QWidget):
    """Folder-shaped label; drag to reorder, double-click to rename."""

    doubleClicked = Signal()

    def __init__(self, name="", parent=None, locked=False):
        super().__init__(parent)
        self._name = name or ""
        self._locked = bool(locked)
        self._drag_start: Optional[QPoint] = None
        self.setObjectName("photoFolderChip")
        self.setFixedSize(92, 64)
        if self._locked:
            self.setCursor(Qt.ArrowCursor)
            self.setToolTip("系统保留；双击在访达中打开。把照片拖回正式相册即可还原")
        else:
            self.setCursor(Qt.OpenHandCursor)
            self.setToolTip("拖动调整顺序；双击改名")

    def setText(self, name):
        self._name = name or ""
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self._drag_start is None:
            super().mouseMoveEvent(event)
            return
        if (
            event.position().toPoint() - self._drag_start
        ).manhattanLength() < QApplication.startDragDistance():
            return
        if self._locked:
            return
        name = (self._name or "").strip()
        if not name:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(ALBUM_ORDER_MIME, QByteArray(name.encode("utf-8")))
        mime.setText(name)
        drag.setMimeData(mime)
        self.setCursor(Qt.ClosedHandCursor)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self._drag_start = None
            # Drop may rebuild rows and delete this chip before exec returns.
            try:
                self.setCursor(Qt.OpenHandCursor)
            except RuntimeError:
                pass

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = None
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


def _paint_cloud_pixmap():
    pix = QPixmap(36, 36)
    pix.fill(Qt.transparent)
    pix.setDevicePixelRatio(2)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(CYAN))
    painter.drawEllipse(QRectF(2, 7, 8, 8))
    painter.drawEllipse(QRectF(6, 4, 9, 9))
    painter.drawEllipse(QRectF(11, 7, 7, 7))
    painter.drawRoundedRect(QRectF(3, 10, 14, 5), 2, 2)
    painter.end()
    return pix


class PhotoAlbumRow(QFrame):
    # True when the album list or row order must be rebuilt (delete/rename folder).
    changed = Signal(bool)
    albumReorderDrop = Signal(str, int)  # album_name, 0=before this row / 1=after
    albumRenamed = Signal(str, str)  # old_name, new_name — emitted before rebuild
    albumDeleted = Signal(str)  # album_name

    def __init__(
        self,
        project_root: Path,
        leg_name: str,
        test_name: str,
        album_name: str,
        project_id: str,
        parent=None,
        remote_root: Optional[Path] = None,
    ):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.remote_root = Path(remote_root) if remote_root else None
        self.leg_name = leg_name or ""
        self.test_name = test_name
        self.album_name = album_name
        self.project_id = project_id
        self._is_spare = album_name == SPARE_ALBUM_NAME
        self.setObjectName("photoAlbumRow")
        self.setAcceptDrops(not self._is_spare)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)

        folder_wrap = QWidget()
        folder_wrap.setFixedSize(102, 74)
        self.chip = FolderChip(album_name, folder_wrap, locked=self._is_spare)
        self.chip.move(0, 8)
        if self._is_spare:
            self.chip.doubleClicked.connect(self._open_in_finder)
        else:
            self.chip.doubleClicked.connect(self._rename_folder)
        self.btn_delete = QPushButton("✕", folder_wrap)
        self.btn_delete.setObjectName("photoThumbDelete")
        self.btn_delete.setFixedSize(18, 18)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setToolTip("删除文件夹")
        self.btn_delete.move(82, 0)
        self.btn_delete.clicked.connect(self._delete_folder)
        self.btn_delete.raise_()
        self.btn_qr = QPushButton("QR", folder_wrap)
        self.btn_qr.setObjectName("photoFolderQr")
        self.btn_qr.setFixedSize(24, 18)
        self.btn_qr.setCursor(Qt.PointingHandCursor)
        self.btn_qr.setToolTip("手机扫码上传照片")
        self.btn_qr.move(0, 0)
        self.btn_qr.clicked.connect(self._open_qr_inbox)
        self.btn_qr.raise_()
        if self._is_spare:
            self.btn_delete.hide()
            self.btn_qr.hide()
        left.addWidget(folder_wrap, 0, Qt.AlignHCenter)

        self.btn_rename_all = QPushButton("打开文件夹" if self._is_spare else "重置照片排序")
        self.btn_rename_all.setObjectName("photoRenameAllLink")
        self.btn_rename_all.setCursor(Qt.PointingHandCursor)
        self.btn_rename_all.setFixedWidth(102)
        if self._is_spare:
            self.btn_rename_all.setToolTip(
                f"在访达中打开「{SPARE_ALBUM_NAME}」；把照片拖回正式相册即可还原"
            )
            self.btn_rename_all.clicked.connect(self._open_in_finder)
        else:
            self.btn_rename_all.setToolTip("按拍摄时间从 001 重新编号（含云端照片）")
            self.btn_rename_all.clicked.connect(self._rename_all)
        left.addWidget(self.btn_rename_all, 0, Qt.AlignHCenter)
        left.addStretch(1)
        root.addLayout(left, 0)
        root.setAlignment(Qt.AlignTop)

        self.gallery = PhotoThumbList(self, in_spare=self._is_spare)
        root.addWidget(self.gallery, stretch=1)
        self._popup = None
        self.reload()

    @property
    def is_spare(self) -> bool:
        return self._is_spare

    def folder(self) -> Path:
        return album_dir(self.project_root, self.leg_name, self.test_name, self.album_name)

    def reload(self):
        self.gallery.clear()
        if self._is_spare:
            photos = list_merged_spare_photos(
                self.project_root,
                self.remote_root,
                self.leg_name,
                self.test_name,
            )
        else:
            photos = list_merged_photos(
                self.project_root,
                self.remote_root,
                self.leg_name,
                self.test_name,
                self.album_name,
            )
        for photo in photos:
            self.gallery.add_photo(photo, self.project_root)
        self.chip.setText(self.album_name)

    def _on_thumb_removed(self):
        self.reload()
        self.changed.emit(False)

    def _on_thumb_renamed(self):
        self.reload()
        self.changed.emit(False)

    def _on_thumb_downloaded(self):
        self.reload()
        self.changed.emit(False)

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
        if self._is_spare:
            return
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
        self.changed.emit(False)

    def _open_in_finder(self):
        folder = self.folder()
        folder.mkdir(parents=True, exist_ok=True)
        target = str(folder)
        if sys.platform == "darwin":
            subprocess.run(["open", target], check=False)
        elif sys.platform == "win32":
            os.startfile(target)
        else:
            subprocess.run(["xdg-open", target], check=False)

    def _rename_all(self):
        if self._is_spare:
            return
        photos = list_merged_photos(
            self.project_root,
            self.remote_root,
            self.leg_name,
            self.test_name,
            self.album_name,
        )
        if not photos:
            QMessageBox.information(self, "提示", "这个文件夹里还没有照片。")
            return
        prefix = self._ask_prefix("重置照片排序")
        if not prefix:
            return
        try:
            rename_all_merged_in_album(
                self.project_root,
                self.remote_root,
                self.leg_name,
                self.test_name,
                self.album_name,
                prefix,
            )
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self.reload()
        self.changed.emit(False)

    def _rename_folder(self):
        if self._is_spare:
            return
        old = self.album_name
        text, ok = QInputDialog.getText(self, "改名", "新的文件夹名称：", text=old)
        if not ok:
            return
        try:
            rename_album(self.project_root, self.leg_name, self.test_name, old, text)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        new = text.strip()
        self.album_name = new
        self.chip.setText(new)
        self.albumRenamed.emit(old, new)

    def _delete_folder(self):
        if self._is_spare:
            return
        answer = QMessageBox.question(
            self,
            "删除照片文件夹",
            "是否删除文件夹？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        name = self.album_name
        delete_album(self.project_root, self.leg_name, self.test_name, name)
        self.albumDeleted.emit(name)

    def _open_qr_inbox(self):
        if self._is_spare:
            return
        try:
            dialog = PhotoInboxDialog(self.folder(), self.album_name, self)
        except OSError as exc:
            QMessageBox.warning(self, "提示", f"无法开启扫码上传：{exc}")
            return

        def _refresh():
            self.reload()
            self.changed.emit(False)

        dialog.photosReceived.connect(_refresh)
        dialog.exec()
        _refresh()

    def _accepts_album_reorder(self, mime: QMimeData) -> bool:
        name = album_name_from_mime(mime)
        return bool(name) and name != self.album_name and name != SPARE_ALBUM_NAME

    def _show_image_popup(self, path: Path):
        from src.ui.test_detail_dialog import StdImagePopup

        pix = QPixmap(str(path))
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

    def _show_preview(self, rel: str):
        try:
            path = preview_path_for_photo(self.project_root, self.remote_root, rel)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self._show_image_popup(path)

    def _show_original(self, rel: str):
        try:
            path = original_view_path(self.project_root, self.remote_root, rel)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self._show_image_popup(path)

    def _rename_photo(self, rel: str):
        current = Path(rel).name
        text, ok = QInputDialog.getText(self, "重命名照片", "新的文件名：", text=current)
        if not ok:
            return
        try:
            rename_merged_photo(self.project_root, self.remote_root, rel, text)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self._on_thumb_renamed()

    def _delete_photo(self, rel: str):
        try:
            move_photo_to_spare(self.project_root, self.remote_root, rel)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self._on_thumb_removed()

    def _download_photo(self, rel: str):
        try:
            download_photo_to_album(self.project_root, self.remote_root, rel)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self._on_thumb_downloaded()

    def _renumber_from_gallery(self):
        if self._is_spare:
            return
        self._write_photo_order(self.gallery.ordered_rels())

    def _apply_photo_reorder(self, src_rel: str, dest: int):
        current = self.gallery.ordered_rels()
        if src_rel not in current:
            return
        old = current.index(src_rel)
        items = list(current)
        item = items.pop(old)
        dest = max(0, min(int(dest), len(items)))
        items.insert(dest, item)
        if items == current:
            return
        self._write_photo_order(items)

    def _write_photo_order(self, items: List[str]):
        if self._is_spare or not items:
            return
        disk = [
            photo.relative_path
            for photo in list_merged_photos(
                self.project_root,
                self.remote_root,
                self.leg_name,
                self.test_name,
                self.album_name,
            )
        ]
        if items == disk:
            return
        prefix = infer_numbered_prefix([Path(rel).name for rel in items]) or self.album_name
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            renumber_merged_photos(
                self.project_root,
                self.remote_root,
                self.leg_name,
                self.test_name,
                self.album_name,
                items,
                prefix,
            )
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        QTimer.singleShot(0, self._finish_photo_reorder)

    def _finish_photo_reorder(self):
        self.reload()
        self.changed.emit(False)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if self._is_spare:
            event.ignore()
            return
        if self._accepts_album_reorder(event.mimeData()):
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if self._is_spare:
            event.ignore()
            return
        if self._accepts_album_reorder(event.mimeData()):
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        event.accept()

    def dropEvent(self, event: QDropEvent):
        if self._is_spare:
            event.ignore()
            return
        name = album_name_from_mime(event.mimeData())
        if name and name != self.album_name:
            event.setDropAction(Qt.MoveAction)
            event.accept()
            local_y = self.mapFromGlobal(event.globalPosition().toPoint()).y()
            insert_at = 0 if local_y < self.height() // 2 else 1
            self.albumReorderDrop.emit(name, insert_at)
            return
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

    def __init__(
        self,
        project_root,
        leg_name,
        test_name,
        project_id,
        parent=None,
        project_state=None,
        form_scroll=None,
        node_data=None,
    ):
        super().__init__(parent)
        self.project_root = Path(project_root) if project_root else None
        self.remote_root = None
        if project_state is not None:
            raw = (getattr(project_state, "source_path", "") or "").strip()
            if raw:
                self.remote_root = Path(raw)
        self.leg_name = leg_name or ""
        self.test_name = test_name or ""
        self.project_id = project_id or ""
        self.project_state = project_state
        self.node_data = node_data
        self._form_scroll = form_scroll
        self._drop_indicator = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setObjectName("dimLabel")
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        toolbar = QHBoxLayout()
        self.btn_template = QPushButton("模版新建")
        self.btn_template.setToolTip("一次开出：试验前、试验中、数据、试验后（已有的跳过）")
        self.btn_custom = QPushButton("自定义新建")
        self.btn_open_spare = QPushButton(f"打开{SPARE_ALBUM_NAME}")
        self.btn_open_spare.setToolTip(
            f"在访达中打开「{SPARE_ALBUM_NAME}」；把照片拖回正式相册即可还原"
        )
        self.btn_template.clicked.connect(self._add_template)
        self.btn_custom.clicked.connect(self._add_custom)
        self.btn_open_spare.clicked.connect(self._open_spare_folder)
        toolbar.addWidget(self.btn_template)
        toolbar.addWidget(self.btn_custom)
        toolbar.addWidget(self.btn_open_spare)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.rows_host = QWidget()
        self.rows_host.setAcceptDrops(True)
        self.rows_host.dragEnterEvent = self._host_drag_enter
        self.rows_host.dragMoveEvent = self._host_drag_move
        self.rows_host.dragLeaveEvent = self._host_drag_leave
        self.rows_host.dropEvent = self._host_drop
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        self._drop_indicator = QFrame(self.rows_host)
        self._drop_indicator.setObjectName("legDropIndicator")
        self._drop_indicator.setFixedHeight(3)
        self._drop_indicator.hide()
        layout.addWidget(self.rows_host)

        self.reload()

    def _preferred_order(self) -> Optional[List[str]]:
        if self.node_data is None:
            return None
        order = getattr(self.node_data, "photo_album_order", None) or []
        return list(order) if order else None

    def _seed_order_from_disk(self) -> List[str]:
        if self.project_root is None:
            return []
        return list_merged_albums(
            self.project_root, self.remote_root, self.leg_name, self.test_name, order=None
        )

    def _write_order(self, names: List[str]) -> None:
        if self.node_data is None:
            return
        self.node_data.photo_album_order = [
            n for n in names if n and n != SPARE_ALBUM_NAME
        ]

    def _row_widgets(self) -> List[PhotoAlbumRow]:
        rows = []
        for i in range(self.rows_layout.count()):
            widget = self.rows_layout.itemAt(i).widget()
            if isinstance(widget, PhotoAlbumRow):
                rows.append(widget)
        return rows

    def _formal_row_widgets(self) -> List[PhotoAlbumRow]:
        return [row for row in self._row_widgets() if not row.is_spare]

    def _spare_row(self) -> Optional[PhotoAlbumRow]:
        for row in self._row_widgets():
            if row.is_spare:
                return row
        return None

    def current_album_order(self) -> List[str]:
        return [row.album_name for row in self._formal_row_widgets()]

    def _reorder_album(self, album_name: str, insert_at: int) -> None:
        if album_name == SPARE_ALBUM_NAME:
            return
        names = self.current_album_order()
        if album_name not in names:
            return
        old = names.index(album_name)
        names.pop(old)
        if insert_at > old:
            insert_at -= 1
        insert_at = max(0, min(insert_at, len(names)))
        names.insert(insert_at, album_name)
        self._write_order(names)
        self._hide_drop_indicator()
        # Rebuild after QDrag.exec returns; deleting FolderChip mid-drag raises
        # "Internal C++ object already deleted".
        QTimer.singleShot(0, self._finish_reorder_ui)

    def _finish_reorder_ui(self) -> None:
        self._reload_preserve_scroll()
        self.changed.emit()

    def _host_accepts_reorder(self, mime: QMimeData) -> bool:
        name = album_name_from_mime(mime)
        return bool(name) and name != SPARE_ALBUM_NAME

    def _host_drag_enter(self, event: QDragEnterEvent):
        if self._host_accepts_reorder(event.mimeData()):
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        event.ignore()

    def _host_drag_move(self, event: QDragMoveEvent):
        if not self._host_accepts_reorder(event.mimeData()):
            self._hide_drop_indicator()
            event.ignore()
            return
        rows = self._formal_row_widgets()
        y = event.position().toPoint().y()
        index = insert_index_for_album_y(self.rows_host, rows, y)
        self._show_drop_indicator(index, rows)
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def _host_drag_leave(self, event: QDragLeaveEvent):
        self._hide_drop_indicator()
        event.accept()

    def _host_drop(self, event: QDropEvent):
        name = album_name_from_mime(event.mimeData())
        self._hide_drop_indicator()
        if not name or name == SPARE_ALBUM_NAME:
            event.ignore()
            return
        rows = self._formal_row_widgets()
        y = event.position().toPoint().y()
        insert_at = insert_index_for_album_y(self.rows_host, rows, y)
        event.setDropAction(Qt.MoveAction)
        event.accept()
        self._reorder_album(name, insert_at)

    def _show_drop_indicator(self, index: int, rows: List[PhotoAlbumRow]) -> None:
        ind = self._drop_indicator
        if ind is None:
            return
        width = max(self.rows_host.width() - 4, 40)
        if not rows:
            y = 0
        elif index <= 0:
            y = rows[0].mapTo(self.rows_host, QPoint(0, 0)).y()
        elif index >= len(rows):
            last = rows[-1]
            y = last.mapTo(self.rows_host, QPoint(0, last.height())).y()
        else:
            y = rows[index].mapTo(self.rows_host, QPoint(0, 0)).y()
        ind.setGeometry(2, max(y - 1, 0), width, 3)
        ind.raise_()
        ind.show()

    def _hide_drop_indicator(self) -> None:
        if self._drop_indicator is not None:
            self._drop_indicator.hide()

    def counts(self):
        if self.project_root is None or not is_usable_test_name(self.test_name):
            return 0, 0
        albums = list_merged_albums(
            self.project_root,
            self.remote_root,
            self.leg_name,
            self.test_name,
            order=self._preferred_order(),
        )
        photos = 0
        for name in albums:
            photos += len(
                list_merged_photos(
                    self.project_root, self.remote_root, self.leg_name, self.test_name, name
                )
            )
        return len(albums), photos

    def _ready(self):
        if self.project_root is None or not self.project_root.is_dir():
            QMessageBox.warning(self, "提示", "本地镜像尚未就绪。")
            return False
        if not is_usable_test_name(self.test_name):
            QMessageBox.warning(self, "提示", "请先在主界面选择试验名称。")
            return False
        return True

    def _ensure_unique_test_name(self) -> bool:
        state = self.project_state
        if state is None or self.node_data is None:
            return True
        leg = find_leg_for_node(state, self.node_data)
        if leg is None:
            return True
        if not state.test_name_is_unique_in_leg(leg.leg_id, self.test_name):
            warn_duplicate_test_names(self)
            return False
        return True

    def _reload_preserve_scroll(self):
        bar = None
        pos = 0
        if self._form_scroll is not None:
            bar = self._form_scroll.verticalScrollBar()
            pos = bar.value()
        self.reload()
        if bar is not None:
            QTimer.singleShot(0, lambda: bar.setValue(min(pos, bar.maximum())))

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
        self.btn_open_spare.setEnabled(enabled)

        if not usable:
            self.lbl_hint.setText("请先在主界面选择试验名称，再管理试验照片。")
            self.lbl_hint.show()
            return
        if not mirrored:
            self.lbl_hint.setText("本地镜像尚未完成，暂时不能写入试验照片。")
            self.lbl_hint.show()
            return

        order = self._preferred_order()
        albums = list_merged_albums(
            self.project_root, self.remote_root, self.leg_name, self.test_name, order=order
        )
        if albums:
            self.lbl_hint.setText(
                "把图片或一层文件夹拖到某一行即可导入；拖动照片可调整先后，拖动左侧文件夹可调整贴图顺序。"
            )
        else:
            self.lbl_hint.setText("还没有照片文件夹。可用「模版新建」一次开出试验前 / 中 / 数据 / 后。")
        self.lbl_hint.show()
        for name in albums:
            self._append_album_row(name)
        self._append_album_row(SPARE_ALBUM_NAME)
        if self._drop_indicator is not None:
            self._drop_indicator.setParent(self.rows_host)
            self._drop_indicator.hide()

    def _append_album_row(self, name: str) -> PhotoAlbumRow:
        row = PhotoAlbumRow(
            self.project_root,
            self.leg_name,
            self.test_name,
            name,
            self.project_id,
            self.rows_host,
            remote_root=self.remote_root,
        )
        row.changed.connect(self._on_row_changed)
        if not row.is_spare:
            row.albumReorderDrop.connect(self._on_row_relative_reorder)
            row.albumRenamed.connect(self._on_album_renamed)
            row.albumDeleted.connect(self._on_album_deleted)
        self.rows_layout.addWidget(row)
        return row

    def _on_row_relative_reorder(self, album_name: str, before_or_after: int):
        sender = self.sender()
        rows = self._formal_row_widgets()
        if not isinstance(sender, PhotoAlbumRow) or sender not in rows:
            return
        insert_at = rows.index(sender) + before_or_after
        self._reorder_album(album_name, insert_at)

    def _on_album_renamed(self, old_name: str, new_name: str):
        order = self._preferred_order()
        if order:
            self._write_order(remap_album_order(order, old_name, new_name))
        else:
            # Lock current on-screen position (chip already shows new_name).
            self._write_order(self.current_album_order())
        self._reload_preserve_scroll()
        self.changed.emit()

    def _on_album_deleted(self, album_name: str):
        order = self._preferred_order()
        if order is not None:
            self._write_order([n for n in order if n != album_name])
        self._reload_preserve_scroll()
        self.changed.emit()

    def _on_row_changed(self, rebuild_rows=False):
        if rebuild_rows:
            self._reload_preserve_scroll()
        else:
            spare = self._spare_row()
            sender = self.sender()
            if spare is not None and sender is not spare:
                spare.reload()
        self.changed.emit()

    def _open_spare_folder(self):
        if not self._ready():
            return
        folder = spare_dir(self.project_root, self.leg_name, self.test_name)
        folder.mkdir(parents=True, exist_ok=True)
        target = str(folder)
        if sys.platform == "darwin":
            subprocess.run(["open", target], check=False)
        elif sys.platform == "win32":
            os.startfile(target)
        else:
            subprocess.run(["xdg-open", target], check=False)

    def _add_template(self):
        if not self._ready():
            return
        if not self._ensure_unique_test_name():
            return
        try:
            created = create_template_albums(self.project_root, self.leg_name, self.test_name)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        if not created and list_merged_albums(
            self.project_root, self.remote_root, self.leg_name, self.test_name, order=self._preferred_order()
        ):
            QMessageBox.information(self, "提示", "模版四个文件夹都已存在。")
        if created and self.node_data is not None:
            order = list(self._preferred_order() or self._seed_order_from_disk())
            for name in created:
                if name not in order:
                    order.append(name)
            self._write_order(order)
        self._reload_preserve_scroll()
        self.changed.emit()

    def _add_custom(self):
        if not self._ready():
            return
        if not self._ensure_unique_test_name():
            return
        text, ok = QInputDialog.getText(self, "自定义新建", "文件夹名称：")
        if not ok:
            return
        try:
            create_album(self.project_root, self.leg_name, self.test_name, text)
        except PhotoError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        name = (text or "").strip()
        if name and self.node_data is not None:
            order = list(self._preferred_order() or self._seed_order_from_disk())
            if name not in order:
                order.append(name)
            self._write_order(order)
        self._reload_preserve_scroll()
        self.changed.emit()
