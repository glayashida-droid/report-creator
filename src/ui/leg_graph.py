import sys
from pathlib import Path

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
                               QLabel, QScrollArea, QComboBox, QFrame, QSizePolicy, QMessageBox,
                               QInputDialog, QStackedWidget)
from PySide6.QtCore import Qt, Signal, QTimer

from src.models.project_state import TestLeg, TestNode
from src.parsers.db_loader import DuplicateStandardError, duplicate_standard_message
from src.ui.test_detail_dialog import TestDetailDialog
from src.io.test_photos import CUSTOM_TEST_NAME, PhotoError, is_usable_test_name, rename_test_dir

PLACEHOLDER_TEST = "请选择试验..."
CUSTOM_TEST = CUSTOM_TEST_NAME


def fill_test_combo(combo: QComboBox, pool: list, current_test: str = ""):
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(PLACEHOLDER_TEST)
    items = list(pool or [])
    current = (current_test or "").strip()
    if current and current not in items and current not in {PLACEHOLDER_TEST, CUSTOM_TEST}:
        items.append(current)
    combo.addItems(items)
    combo.addItem(CUSTOM_TEST)
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
        self.setObjectName("testNodeCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Plain)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)

        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        self.combo.lineEdit().setPlaceholderText(PLACEHOLDER_TEST)
        fill_test_combo(self.combo, self.candidate_pool, self.node_data.test_name)
        self.combo.currentTextChanged.connect(self.on_test_changed)
        self.combo.lineEdit().editingFinished.connect(self.on_test_edit_finished)
        self.combo.activated.connect(self._on_combo_activated)
        grid.addWidget(self.combo, 0, 0)

        self.lbl_complete = QLabel("✓")
        self.lbl_complete.setObjectName("nodeCompleteMark")
        self.lbl_complete.setToolTip("标准、关键参数、设备、结果均已填写")
        self.lbl_complete.setAlignment(Qt.AlignCenter)
        self.lbl_complete.setFixedWidth(16)
        grid.addWidget(self.lbl_complete, 0, 1, Qt.AlignCenter)

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
        grid.addLayout(btn_layout, 1, 0, 1, 2)
        layout.addLayout(grid)
        self._refresh_complete_mark()

    def _refresh_complete_mark(self):
        self.lbl_complete.setVisible(self.node_data.is_detail_complete())

    def show_detail(self):
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

    def _restore_committed_combo(self):
        self.combo.blockSignals(True)
        fill_test_combo(self.combo, self.candidate_pool, self._committed_name)
        self.combo.blockSignals(False)
        self.node_data.test_name = self._committed_name
        self._refresh_complete_mark()
        self.node_updated.emit()

    def _prompt_custom_name(self):
        text, ok = QInputDialog.getText(
            self,
            "自定义试验名称",
            "试验名称：",
            text=self._committed_name or "",
        )
        if not ok:
            self._restore_committed_combo()
            return
        name = (text or "").strip()
        if not is_usable_test_name(name):
            QMessageBox.warning(self, "提示", "请输入有效的试验名称")
            self._restore_committed_combo()
            return
        self.combo.blockSignals(True)
        fill_test_combo(self.combo, self.candidate_pool, name)
        self.combo.blockSignals(False)
        self._commit_test_name(name)

    def _on_combo_activated(self, *_args):
        if self.combo.currentText().strip() == CUSTOM_TEST:
            self._prompt_custom_name()
            return
        self.on_test_edit_finished()

    def _project_state(self):
        widget = self.parent()
        while widget is not None:
            state = getattr(widget, "state", None)
            if state is not None:
                return state
            widget = widget.parent()
        return None

    def _commit_test_name(self, name):
        old = self._committed_name
        self.node_data.test_name = name
        if old == name:
            self._refresh_complete_mark()
            self.node_updated.emit()
            return
        state = self._project_state()
        root = Path(state.project_path) if state and getattr(state, "project_path", "") else None
        if root is not None and root.is_dir() and is_usable_test_name(old):
            try:
                rename_test_dir(root, old, name)
            except PhotoError as exc:
                QMessageBox.warning(self, "无法改名", str(exc))
                self.combo.blockSignals(True)
                fill_test_combo(self.combo, self.candidate_pool, old)
                self.combo.blockSignals(False)
                self.node_data.test_name = old
                self._refresh_complete_mark()
                self.node_updated.emit()
                return
        self._committed_name = name
        self._refresh_complete_mark()
        self.node_updated.emit()

    def on_test_changed(self, text):
        name = self._normalized_test_name(text)
        if self.node_data.test_name == name:
            return
        self.node_data.test_name = name
        self._refresh_complete_mark()
        self.node_updated.emit()

    def on_test_edit_finished(self):
        name = self._normalized_test_name(self.combo.currentText())
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
        
    def add_node_widget(self, node_data: TestNode):
        nw = TestNodeWidget(node_data, self.candidate_pool, db_loader=self.db_loader)
        nw.node_updated.connect(self.leg_updated)
        nw.node_deleted.connect(self.on_node_deleted)
        self.node_widgets.append(nw)
        self.nodes_layout.addWidget(nw)
        
    def on_add_node(self):
        new_node = TestNode(test_name="")
        self.leg_data.nodes.append(new_node)
        self.add_node_widget(new_node)
        self.leg_updated.emit()
        
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
        self.btn_save = QPushButton("保存项目")
        _style_toolbar_button(self.btn_save, "legToolbarAccentButton")
        self.btn_load_state = QPushButton("加载项目")
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
