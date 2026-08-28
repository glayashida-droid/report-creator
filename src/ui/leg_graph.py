import sys
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QScrollArea, QComboBox, QFrame, QSizePolicy, QMessageBox,
                               QStackedWidget)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QResizeEvent

from src.models.project_state import TestLeg, TestNode
from src.parsers.db_loader import DuplicateStandardError, duplicate_standard_message
from src.ui.candidate_pool import CANDIDATE_TEST_MIME, candidate_test_from_mime, pool_drag_active
from src.ui.test_detail_dialog import TestDetailDialog
from src.io.test_photos import (
    CUSTOM_TEST_NAME,
    PhotoError,
    is_usable_test_name,
    rename_test_dir,
    test_dir,
)
from src.io.data_tables import retarget_node_data_tables

PLACEHOLDER_TEST = "请选择试验..."
CUSTOM_TEST = CUSTOM_TEST_NAME


def insert_index_for_y(leg_widget, node_widgets, y: int) -> int:
    """Return list index to insert before, based on Y in leg_widget coordinates."""
    if not node_widgets:
        return 0
    for i, node_widget in enumerate(node_widgets):
        top = node_widget.mapTo(leg_widget, QPoint(0, 0)).y()
        center = top + node_widget.height() // 2
        if y < center:
            return i
    return len(node_widgets)


def fill_test_combo(combo: QComboBox, pool: list, current_test: str = ""):
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(PLACEHOLDER_TEST)
    items = list(pool or [])
    current = (current_test or "").strip()
    if current and current not in items and current not in {PLACEHOLDER_TEST, CUSTOM_TEST}:
        items.append(current)
    combo.addItems(items)
    if current and current != CUSTOM_TEST:
        combo.setCurrentText(current)
        combo.setEditText(current)
    else:
        combo.setCurrentIndex(0)
        combo.setEditText("")
    combo.blockSignals(False)


class TestNodeWidget(QFrame):
    """A single test node card inside a Leg"""
    node_updated = Signal()
    node_deleted = Signal(object) # passes self
    
    def __init__(self, node_data: TestNode, candidate_pool: list, parent=None, db_loader=None):
        super().__init__(parent)
        self.node_data = node_data
        self.candidate_pool = candidate_pool
        self.db_loader = db_loader
        self._committed_name = self._normalized_test_name(node_data.test_name)
        self._initializing = True
        self.setObjectName("testNodeCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Plain)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)

        # Two mirrored HBoxes keep outer edges flush whether or not the
        # complete mark is visible (grid column spacing used to leave a 4px gap).
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(4)

        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        # Pool chips also carry text/plain; if the line edit accepts drops, Qt
        # appends into the name and LegWidget never gets a before/after insert.
        self.combo.setAcceptDrops(False)
        le = self.combo.lineEdit()
        le.setAcceptDrops(False)
        le.setPlaceholderText(PLACEHOLDER_TEST)
        fill_test_combo(self.combo, self.candidate_pool, self.node_data.test_name)
        self.combo.currentTextChanged.connect(self.on_test_changed)
        self.combo.lineEdit().editingFinished.connect(self.on_test_edit_finished)
        self.combo.activated.connect(self.on_test_edit_finished)
        top_row.addWidget(self.combo, stretch=1)

        self.lbl_complete = QLabel("✓")
        self.lbl_complete.setObjectName("nodeCompleteMark")
        self.lbl_complete.setToolTip("标准、关键参数、设备、结果均已填写")
        self.lbl_complete.setAlignment(Qt.AlignCenter)
        self.lbl_complete.setFixedWidth(16)
        top_row.addWidget(self.lbl_complete, alignment=Qt.AlignCenter)
        layout.addLayout(top_row)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(6)

        self.btn_detail = QPushButton("编辑明细")
        self.btn_detail.setObjectName("nodeDetailButton")
        self.btn_detail.setFixedHeight(28)
        self.btn_detail.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_detail.clicked.connect(self.show_detail)
        self.btn_delete = QPushButton("✕")
        self.btn_delete.setObjectName("nodeDeleteButton")
        self.btn_delete.setFixedSize(28, 28)
        self.btn_delete.setToolTip("删除该试验")
        self.btn_delete.clicked.connect(lambda: self.node_deleted.emit(self))

        btn_layout.addWidget(self.btn_detail, stretch=1)
        btn_layout.addWidget(self.btn_delete)
        layout.addLayout(btn_layout)
        self._refresh_complete_mark()
        self._sync_detail_button()
        self._initializing = False

    def _refresh_complete_mark(self):
        self.lbl_complete.setVisible(self.node_data.is_detail_complete())

    def _sync_detail_button(self):
        ok = is_usable_test_name(self._committed_name)
        self.btn_detail.setEnabled(ok)
        self.btn_detail.setToolTip("" if ok else "请先选择或输入试验名称")

    def show_detail(self):
        if not is_usable_test_name(self._committed_name):
            QMessageBox.warning(self, "提示", "请先选择或输入试验名称")
            return
        if not self.db_loader:
            QMessageBox.warning(self, "提示", "标准库尚未就绪，无法编辑明细")
            return

        try:
            standards = self.db_loader.load_standards()
        except DuplicateStandardError as exc:
            QMessageBox.warning(self, "提示", duplicate_standard_message(exc))
            return

        dialog = TestDetailDialog(
            self.node_data,
            standards,
            self.db_loader.load_equipments(),
            self
        )
        if dialog.exec():
            self._refresh_complete_mark()
            self.node_updated.emit()

    def _normalized_test_name(self, text: str) -> str:
        name = (text or "").strip()
        if name in {PLACEHOLDER_TEST, CUSTOM_TEST}:
            return ""
        return name

    def _project_state(self):
        widget = self.parent()
        while widget is not None:
            state = getattr(widget, "state", None)
            if state is not None:
                return state
            widget = widget.parent()
        return None

    def resync_from_committed(self) -> None:
        """Restore combo text to the last committed name without touching disk."""
        if self._normalized_test_name(self.combo.currentText()) == self._committed_name:
            self.node_data.test_name = self._committed_name
            return
        self.combo.blockSignals(True)
        fill_test_combo(self.combo, self.candidate_pool, self._committed_name)
        self.combo.blockSignals(False)
        self.node_data.test_name = self._committed_name
        self._refresh_complete_mark()
        self._sync_detail_button()

    def _rollback_test_name(self, old: str) -> None:
        self._committed_name = old
        self.resync_from_committed()
        self.node_updated.emit()

    def _warn_rename_failed(self, message: str, old: str) -> None:
        def show() -> None:
            QMessageBox.warning(self, "无法改名", message)
            self._rollback_test_name(old)

        # Never nest a modal inside drag.exec(); defer until the event loop is free.
        QTimer.singleShot(0, show)

    def _other_nodes_use_name(self, name: str) -> bool:
        needle = (name or "").strip()
        if not needle:
            return False
        state = self._project_state()
        if state is None:
            return False
        for leg in state.legs or []:
            for node in leg.nodes or []:
                if node is self.node_data:
                    continue
                if (node.test_name or "").strip() == needle:
                    return True
        return False

    def _should_rename_folder(self, old: str, new: str) -> bool:
        """Only move disk folders when this node uniquely owns the old name."""
        if not is_usable_test_name(old) or not is_usable_test_name(new):
            return False
        if old == new:
            return False
        if self._other_nodes_use_name(old):
            return False
        return True

    def _commit_test_name(self, name):
        old = self._committed_name
        self.node_data.test_name = name
        if old == name:
            self._refresh_complete_mark()
            self.node_updated.emit()
            return
        state = self._project_state()
        root = Path(state.project_path) if state and getattr(state, "project_path", "") else None
        retarget_paths = False
        if (
            root is not None
            and root.is_dir()
            and self._should_rename_folder(old, name)
        ):
            dest = test_dir(root, name)
            if dest.exists():
                # Temporary duplicate names are allowed while editing; skip move.
                pass
            else:
                try:
                    rename_test_dir(root, old, name)
                except PhotoError as exc:
                    self._warn_rename_failed(str(exc), old)
                    return
                retarget_paths = True
        elif not self._other_nodes_use_name(old):
            # No shared owner of the old name: keep index paths aligned with the new name.
            retarget_paths = True
        if retarget_paths:
            retarget_node_data_tables(self.node_data, old, name)
        self._committed_name = name
        self._refresh_complete_mark()
        self._sync_detail_button()
        self.node_updated.emit()

    def on_test_changed(self, text):
        if self._initializing or pool_drag_active():
            return
        name = self._normalized_test_name(text)
        if self.node_data.test_name == name:
            return
        self.node_data.test_name = name
        self._refresh_complete_mark()
        self.node_updated.emit()

    def on_test_edit_finished(self):
        if self._initializing or pool_drag_active():
            return
        name = self._normalized_test_name(self.combo.currentText())
        if name == self._committed_name:
            # Combo may have drifted visually; snap display without a rename.
            if self.combo.currentText().strip() != name:
                self.resync_from_committed()
            return
        if self.combo.currentText() != name:
            self.combo.blockSignals(True)
            self.combo.setEditText(name)
            self.combo.blockSignals(False)
        self._commit_test_name(name)

class LegWidget(QFrame):
    """A single Leg column containing multiple Test Nodes"""
    leg_updated = Signal()
    leg_deleted = Signal(object)
    
    def __init__(self, leg_data: TestLeg, candidate_pool: list, parent=None, db_loader=None):
        super().__init__(parent)
        self.leg_data = leg_data
        self.candidate_pool = candidate_pool
        self.db_loader = db_loader
        self.node_widgets = []
        
        self.setObjectName("legCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Plain)
        self.setMinimumWidth(220)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.setAcceptDrops(True)
        self._drop_index: Optional[int] = None
        self._drop_indicator = QFrame(self)
        self._drop_indicator.setObjectName("legDropIndicator")
        self._drop_indicator.setFixedHeight(2)
        self._drop_indicator.hide()

        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(8)
        self.layout.setAlignment(Qt.AlignTop)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        lbl_title = QLabel(f"<b>{self.leg_data.leg_name}</b>")
        btn_del = QPushButton("删除")
        btn_del.setObjectName("accentButton")
        btn_del.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        btn_del.clicked.connect(lambda: self.leg_deleted.emit(self))
        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(btn_del)
        self.layout.addLayout(header_layout)

        self.nodes_layout = QVBoxLayout()
        self.nodes_layout.setContentsMargins(0, 0, 0, 0)
        self.nodes_layout.setSpacing(6)
        self.nodes_layout.setAlignment(Qt.AlignTop)
        self.layout.addLayout(self.nodes_layout)

        for node_data in self.leg_data.nodes:
            self.add_node_widget(node_data)

        self.btn_add_node = QPushButton("+ 添加试验")
        self.btn_add_node.clicked.connect(self.on_add_node)
        self.layout.addWidget(self.btn_add_node)

    def _accepts_candidate_drop(self, mime) -> bool:
        return mime.hasFormat(CANDIDATE_TEST_MIME) and bool(candidate_test_from_mime(mime))

    def _set_drop_active(self, active: bool) -> None:
        if self.property("dropActive") == active:
            return
        self.setProperty("dropActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def _insert_index_at(self, pos: QPoint) -> int:
        return insert_index_for_y(self, self.node_widgets, pos.y())

    def _indicator_y_for_index(self, index: int) -> int:
        gap = 3
        if not self.node_widgets:
            if self.btn_add_node is not None:
                return max(self.btn_add_node.mapTo(self, QPoint(0, 0)).y() - 12, 36)
            return 36
        if index <= 0:
            node = self.node_widgets[0]
            return node.mapTo(self, QPoint(0, 0)).y() - gap
        if index >= len(self.node_widgets):
            node = self.node_widgets[-1]
            return node.mapTo(self, QPoint(0, node.height())).y() + gap
        node = self.node_widgets[index]
        return node.mapTo(self, QPoint(0, 0)).y() - gap

    def _show_drop_indicator(self, index: int) -> None:
        self._drop_index = index
        margin = self.layout.contentsMargins().left()
        y = self._indicator_y_for_index(index)
        self._drop_indicator.setGeometry(margin, y, max(self.width() - margin * 2, 40), 2)
        self._drop_indicator.show()
        self._drop_indicator.raise_()

    def _hide_drop_indicator(self) -> None:
        self._drop_index = None
        self._drop_indicator.hide()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._accepts_candidate_drop(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self._set_drop_active(True)
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if not self._accepts_candidate_drop(event.mimeData()):
            event.ignore()
            return
        index = self._insert_index_at(event.position().toPoint())
        self._show_drop_indicator(index)
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._hide_drop_indicator()
        self._set_drop_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._hide_drop_indicator()
        self._set_drop_active(False)
        if not self._accepts_candidate_drop(event.mimeData()):
            event.ignore()
            return
        name = candidate_test_from_mime(event.mimeData())
        index = self._insert_index_at(event.position().toPoint())
        event.setDropAction(Qt.CopyAction)
        event.accept()
        # Defer insert until drag.exec() returns — avoids nested modal loops / frozen OK buttons.
        QTimer.singleShot(0, lambda n=name, i=index: self._insert_from_pool_drop(i, n))

    def _insert_from_pool_drop(self, index: int, test_name: str) -> None:
        """Drop-in only adds a node; never renames sibling folders."""
        for nw in self.node_widgets:
            nw.resync_from_committed()
        focused = QApplication.focusWidget()
        if focused is not None:
            focused.clearFocus()
        self.insert_node_at(index, test_name)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._drop_index is not None:
            self._show_drop_indicator(self._drop_index)
        
    def add_node_widget(self, node_data: TestNode, index: Optional[int] = None):
        nw = TestNodeWidget(node_data, self.candidate_pool, db_loader=self.db_loader)
        nw.node_updated.connect(self.leg_updated)
        nw.node_deleted.connect(self.on_node_deleted)
        if index is None:
            self.node_widgets.append(nw)
            self.nodes_layout.addWidget(nw)
        else:
            self.node_widgets.insert(index, nw)
            self.nodes_layout.insertWidget(index, nw)

    def insert_node_at(self, index: int, test_name: str = "") -> None:
        # Assign name at creation — no rename_test_dir path.
        new_node = TestNode(test_name=(test_name or "").strip())
        index = max(0, min(index, len(self.leg_data.nodes)))
        self.leg_data.nodes.insert(index, new_node)
        self.add_node_widget(new_node, index)
        self.leg_updated.emit()
        
    def on_add_node(self):
        self.insert_node_at(len(self.leg_data.nodes))
        
    def on_node_deleted(self, nw: TestNodeWidget):
        self.node_widgets.remove(nw)
        self.leg_data.nodes.remove(nw.node_data)
        nw.setParent(None)
        nw.deleteLater()
        self.leg_updated.emit()
        
    def update_pool(self, new_pool: list):
        self.candidate_pool = new_pool
        for nw in self.node_widgets:
            nw.candidate_pool = new_pool
            fill_test_combo(nw.combo, new_pool, nw.node_data.test_name)

from src.parsers.db_loader import BaseDataLoader
from src.ui.gantt_chart import GanttChartWidget

_TOOLBAR_BTN_H = 28


def _style_toolbar_button(btn: QPushButton, object_name: str = "legToolbarButton") -> None:
    btn.setObjectName(object_name)
    btn.setFixedHeight(_TOOLBAR_BTN_H)
    btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)


def _style_zoom_button(btn: QPushButton) -> None:
    btn.setObjectName("ganttZoomButton")
    btn.setFixedSize(_TOOLBAR_BTN_H, _TOOLBAR_BTN_H)
    btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


class LegGraphArea(QWidget):
    """The main scrollable area containing all Legs"""
    structure_changed = Signal()
    VIEW_LAYOUT = 0
    VIEW_GANTT = 1

    def __init__(self, state_ref, parent=None):
        super().__init__(parent)
        self._state_ref = state_ref
        self.db_loader = BaseDataLoader() # Initialize loader here
        self.leg_widgets = []
        self.init_ui()

    @property
    def state(self):
        return self._state_ref

    @state.setter
    def state(self, value):
        self._state_ref = value
        if hasattr(self, "gantt_chart"):
            self.gantt_chart.state = value
            if self.is_gantt_mode():
                self.gantt_chart.refresh()
        
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Shared toolbar (layout controls + gantt toggle)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.btn_view_toggle = QPushButton("甘特图")
        self.btn_view_toggle.clicked.connect(self.toggle_view_mode)
        _style_toolbar_button(self.btn_view_toggle)
        self.btn_add_leg = QPushButton("+ 添加 Leg")
        self.btn_add_leg.clicked.connect(self.add_leg)
        _style_toolbar_button(self.btn_add_leg)
        self.btn_gantt_zoom_out = QPushButton("-")
        _style_zoom_button(self.btn_gantt_zoom_out)
        self.btn_gantt_zoom_out.clicked.connect(lambda: self.zoom_gantt(-1))
        self.btn_gantt_zoom_in = QPushButton("+")
        _style_zoom_button(self.btn_gantt_zoom_in)
        self.btn_gantt_zoom_in.clicked.connect(lambda: self.zoom_gantt(1))
        self.btn_save = QPushButton("保存明细")
        _style_toolbar_button(self.btn_save, "legToolbarAccentButton")
        self.btn_load_state = QPushButton("加载明细")
        _style_toolbar_button(self.btn_load_state)
        self.btn_save_template = QPushButton("存为模板")
        _style_toolbar_button(self.btn_save_template)
        self.btn_import_template = QPushButton("导入模板")
        _style_toolbar_button(self.btn_import_template)
        toolbar.addWidget(self.btn_view_toggle, 0, Qt.AlignVCenter)
        toolbar.addWidget(self.btn_add_leg, 0, Qt.AlignVCenter)
        toolbar.addWidget(self.btn_gantt_zoom_out, 0, Qt.AlignVCenter)
        toolbar.addWidget(self.btn_gantt_zoom_in, 0, Qt.AlignVCenter)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_save, 0, Qt.AlignVCenter)
        toolbar.addWidget(self.btn_load_state, 0, Qt.AlignVCenter)
        toolbar.addWidget(self.btn_save_template, 0, Qt.AlignVCenter)
        toolbar.addWidget(self.btn_import_template, 0, Qt.AlignVCenter)
        main_layout.addLayout(toolbar)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.layout_page = QWidget()
        layout_page_layout = QVBoxLayout(self.layout_page)
        layout_page_layout.setContentsMargins(0, 0, 0, 0)
        layout_page_layout.setSpacing(0)

        # Scroll Area for Legs
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        
        self.scroll_content = QWidget()
        self.scroll_content.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.legs_layout = QHBoxLayout(self.scroll_content)
        self.legs_layout.setContentsMargins(8, 8, 8, 8)
        self.legs_layout.setSpacing(12)
        self.legs_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.legs_layout.addStretch(1)

        self.scroll_area.setWidget(self.scroll_content)
        layout_page_layout.addWidget(self.scroll_area, stretch=1)

        self.gantt_chart = GanttChartWidget(self.state)
        self.gantt_chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.gantt_chart.schedule_changed.connect(self.structure_changed.emit)

        self.stack.addWidget(self.layout_page)
        self.stack.addWidget(self.gantt_chart)
        main_layout.addWidget(self.stack, stretch=1)
        self._sync_view_toolbar()
        
    def is_gantt_mode(self) -> bool:
        return self.stack.currentIndex() == self.VIEW_GANTT

    def _sync_view_toolbar(self) -> None:
        gantt = self.is_gantt_mode()
        self.btn_add_leg.setVisible(not gantt)
        self.btn_save.setVisible(not gantt)
        self.btn_load_state.setVisible(not gantt)
        self.btn_save_template.setVisible(not gantt)
        self.btn_import_template.setVisible(not gantt)
        self.btn_gantt_zoom_out.setVisible(gantt)
        self.btn_gantt_zoom_in.setVisible(gantt)
        self.btn_view_toggle.setText("Leg排布" if gantt else "甘特图")

    def set_gantt_mode(self, enabled: bool) -> None:
        self.stack.setCurrentIndex(self.VIEW_GANTT if enabled else self.VIEW_LAYOUT)
        self._sync_view_toolbar()
        if enabled:
            self.gantt_chart.state = self.state
            QTimer.singleShot(0, self._enter_gantt_mode)

    def _enter_gantt_mode(self) -> None:
        self.gantt_chart.refresh()
        self.gantt_chart.warn_if_overlaps()

    def toggle_view_mode(self) -> None:
        self.set_gantt_mode(not self.is_gantt_mode())

    def zoom_gantt(self, delta: int) -> None:
        if not self.is_gantt_mode():
            return
        self.gantt_chart.zoom_step(delta)

    def reload_from_state(self):
        # Clear existing
        for lw in self.leg_widgets:
            lw.setParent(None)
            lw.deleteLater()
        self.leg_widgets.clear()
        
        # Load from state
        for leg_data in self.state.legs:
            self._add_leg_widget(leg_data)
        if self.is_gantt_mode():
            self.gantt_chart.refresh()
            self.gantt_chart.warn_if_overlaps()
        self.structure_changed.emit()
            
    def add_leg(self):
        idx = len(self.state.legs) + 1
        leg_data = TestLeg(leg_id=f"L{idx}", leg_name=f"Leg {idx}")
        self.state.legs.append(leg_data)
        self._add_leg_widget(leg_data)
        self.structure_changed.emit()
        
    def _picker_pool(self):
        if hasattr(self.state, "combo_pool"):
            return self.state.combo_pool()
        return list(self.state.candidate_pool or [])

    def _add_leg_widget(self, leg_data):
        lw = LegWidget(leg_data, self._picker_pool(), db_loader=self.db_loader)
        lw.leg_deleted.connect(self.on_leg_deleted)
        lw.leg_updated.connect(self.structure_changed.emit)
        self.leg_widgets.append(lw)
        insert_at = max(self.legs_layout.count() - 1, 0)
        self.legs_layout.insertWidget(insert_at, lw, 0, Qt.AlignTop)
        
    def on_leg_deleted(self, lw: LegWidget):
        self.leg_widgets.remove(lw)
        self.state.legs.remove(lw.leg_data)
        lw.setParent(None)
        lw.deleteLater()
        self.structure_changed.emit()
        
    def notify_pool_changed(self):
        pool = self._picker_pool()
        for lw in self.leg_widgets:
            lw.update_pool(pool)
