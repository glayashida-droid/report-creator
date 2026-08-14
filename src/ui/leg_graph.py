import sys
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
                               QLabel, QScrollArea, QComboBox, QFrame, QSizePolicy)
from PySide6.QtCore import Qt, Signal

from src.models.project_state import TestLeg, TestNode

from src.ui.test_detail_dialog import TestDetailDialog

PLACEHOLDER_TEST = "请选择试验..."


def fill_test_combo(combo: QComboBox, pool: list, current_test: str = ""):
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(PLACEHOLDER_TEST)
    items = list(pool or [])
    current = (current_test or "").strip()
    if current and current not in items and current != PLACEHOLDER_TEST:
        items.append(current)
    combo.addItems(items)
    if current:
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
    
    def __init__(self, node_data: TestNode, candidate_pool: list, parent=None):
        super().__init__(parent)
        self.node_data = node_data
        self.candidate_pool = candidate_pool
        # Need reference to standards/equipments. We will get them from LegGraphArea -> LegWidget
        self.db_loader = None 
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
        grid.addWidget(self.combo, 0, 0)

        self.lbl_complete = QLabel("✓")
        self.lbl_complete.setObjectName("nodeCompleteMark")
        self.lbl_complete.setToolTip("标准、设备、结果均已填写")
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
        grid.addLayout(btn_layout, 1, 0)
        layout.addLayout(grid)
        self._refresh_complete_mark()

    def _refresh_complete_mark(self):
        self.lbl_complete.setVisible(self.node_data.is_detail_complete())

    def show_detail(self):
        if not self.db_loader:
            return

        dialog = TestDetailDialog(
            self.node_data,
            self.db_loader.load_standards(),
            self.db_loader.load_equipments(),
            self
        )
        if dialog.exec():
            self._refresh_complete_mark()
            self.node_updated.emit()

    def _normalized_test_name(self, text: str) -> str:
        name = (text or "").strip()
        if name == PLACEHOLDER_TEST:
            return ""
        return name

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
            self.combo.setEditText(name)
        self.on_test_changed(name)

class LegWidget(QFrame):
    """A single Leg column containing multiple Test Nodes"""
    leg_updated = Signal()
    leg_deleted = Signal(object)
    
    def __init__(self, leg_data: TestLeg, candidate_pool: list, parent=None):
        super().__init__(parent)
        self.leg_data = leg_data
        self.candidate_pool = candidate_pool
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
        nw = TestNodeWidget(node_data, self.candidate_pool)
        # Pass db_loader down from parent
        p = self.parent()
        while p and not hasattr(p, 'db_loader'):
            p = p.parent()
        if p and hasattr(p, 'db_loader'):
            nw.db_loader = p.db_loader
            
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

class LegGraphArea(QWidget):
    """The main scrollable area containing all Legs"""
    structure_changed = Signal()

    def __init__(self, state_ref, parent=None):
        super().__init__(parent)
        self.state = state_ref
        self.db_loader = BaseDataLoader() # Initialize loader here
        self.leg_widgets = []
        self.init_ui()
        
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        
        # Toolbar
        toolbar = QHBoxLayout()
        self.btn_add_leg = QPushButton("+ 添加 Leg")
        self.btn_add_leg.clicked.connect(self.add_leg)
        self.btn_save = QPushButton("保存状态")
        self.btn_save.setObjectName("accentButton")
        self.btn_load_state = QPushButton("加载状态")
        self.btn_save_template = QPushButton("保存为模板")
        self.btn_import_template = QPushButton("导入模板")
        toolbar.addWidget(self.btn_add_leg)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_save)
        toolbar.addWidget(self.btn_load_state)
        toolbar.addWidget(self.btn_save_template)
        toolbar.addWidget(self.btn_import_template)
        main_layout.addLayout(toolbar)
        
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
        main_layout.addWidget(self.scroll_area)
        
    def reload_from_state(self):
        # Clear existing
        for lw in self.leg_widgets:
            lw.setParent(None)
            lw.deleteLater()
        self.leg_widgets.clear()
        
        # Load from state
        for leg_data in self.state.legs:
            self._add_leg_widget(leg_data)
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
        lw = LegWidget(leg_data, self._picker_pool())
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
