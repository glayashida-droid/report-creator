import sys
import re
import subprocess
from typing import Optional
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QSplitter, QComboBox, QMessageBox,
    QDateEdit, QFileDialog, QFormLayout, QScrollArea, QSizePolicy, QFrame,
    QInputDialog, QButtonGroup,
)
from PySide6.QtCore import Qt, QDate, QThread, Signal

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.models.project_state import ProjectState
from application_parser import parse_application, prepare_excel_bytes
from src.parsers.pdf_parser import QuotationParser
from src.io.project_mirror import incremental_copy, list_saved_projects, local_project_dir
from src.io.leg_templates import (
    TemplateExistsError,
    TemplateNameError,
    apply_leg_template,
    list_leg_templates,
    load_leg_template as read_leg_template,
    save_leg_template as write_leg_template,
)
from src.ui.leg_graph import LegGraphArea
from src.ui.load_state_dialog import LoadStateDialog
from src.ui.leg_template_dialog import ImportTemplateDialog
from src.ui.candidate_pool import CandidatePoolList


class MirrorWorker(QThread):
    succeeded = Signal(int, str)
    failed = Signal(int, str)

    def __init__(self, src: Path, dest: Path, generation: int, parent=None):
        super().__init__(parent)
        self._src = Path(src)
        self._dest = Path(dest)
        self._generation = generation

    def run(self):
        try:
            ok = incremental_copy(
                self._src, self._dest, cancelled=self.isInterruptionRequested
            )
            if not ok:
                return
            self.succeeded.emit(self._generation, str(self._dest))
        except Exception as e:
            self.failed.emit(self._generation, str(e))


APP_VERSION = "1.1.1"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Report Creator---Ver{APP_VERSION}  Design by IKARUGA")
        self.resize(1100, 620)
        self.setMinimumSize(880, 480)
        self.state = ProjectState()
        self._project_path = None  # type: Optional[Path]
        self._source_path = None  # type: Optional[Path]
        self._local_path = None  # type: Optional[Path]
        self._mirror_ready = False
        self._mirror_worker = None  # type: Optional[MirrorWorker]
        self._mirror_gen = 0
        self._abandoned_workers = []
        self._is_dirty = False

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(8)

        # 1. Project Locator (compact)
        top_panel = QGroupBox("项目定位")
        top_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        top_outer = QVBoxLayout(top_panel)
        top_outer.setContentsMargins(8, 6, 8, 6)
        top_outer.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.txt_project_path = QLineEdit()
        self.txt_project_path.setPlaceholderText(
            "粘贴项目文件夹路径 / 链接，或点击右侧选择目录"
        )
        self.txt_project_path.returnPressed.connect(self.load_from_pasted_path)

        btn_browse = QPushButton("选择目录…")
        btn_browse.setObjectName("accentButton")
        btn_browse.setFixedWidth(100)
        btn_browse.clicked.connect(self.browse_project_folder)

        btn_load = QPushButton("加载")
        btn_load.setFixedWidth(64)
        btn_load.clicked.connect(self.load_from_pasted_path)

        row.addWidget(QLabel("路径:"))
        row.addWidget(self.txt_project_path, stretch=1)
        row.addWidget(btn_browse)
        row.addWidget(btn_load)
        top_outer.addLayout(row)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        self.lbl_project_id = QLabel("项目号: —")
        self.lbl_project_id.setObjectName("dimLabel")
        self.lbl_mirror_status = QLabel("")
        self.lbl_mirror_status.setObjectName("dimLabel")
        meta_row.addWidget(self.lbl_project_id)
        meta_row.addStretch()
        meta_row.addWidget(self.lbl_mirror_status)
        top_outer.addLayout(meta_row)

        main_layout.addWidget(top_panel)

        splitter = QSplitter(Qt.Horizontal)

        # 2. Left Panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 2.1 Project overview — all homepage fields
        info_group = QGroupBox("项目概况")
        info_group.setObjectName("overviewGroup")
        info_layout = QVBoxLayout(info_group)
        info_layout.setContentsMargins(10, 18, 10, 10)
        info_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(180)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        form_host = QWidget()
        self.info_form = QFormLayout(form_host)
        self.info_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.info_form.setFormAlignment(Qt.AlignTop)
        self.info_form.setHorizontalSpacing(12)
        self.info_form.setVerticalSpacing(4)
        self._info_placeholder = QLabel("未加载")
        self._info_placeholder.setObjectName("dimLabel")
        self.info_form.addRow(self._info_placeholder)
        scroll.setWidget(form_host)
        info_layout.addWidget(scroll, stretch=1)

        date_bar = QWidget()
        date_bar.setObjectName("overviewDates")
        date_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        date_layout = QHBoxLayout(date_bar)
        date_layout.setContentsMargins(0, 4, 0, 0)
        date_layout.setSpacing(8)

        def make_date_column(label_text):
            col = QVBoxLayout()
            col.setSpacing(2)
            col.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label_text)
            lbl.setObjectName("dimLabel")
            date_edit = QDateEdit()
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("yyyy-MM-dd")
            date_edit.setDate(QDate.currentDate())
            date_edit.lineEdit().setReadOnly(True)
            col.addWidget(lbl)
            col.addWidget(date_edit)
            return col, date_edit

        col1, self.date_receive = make_date_column("接收日期")
        col2, self.date_start = make_date_column("检测开始")
        col3, self.date_end = make_date_column("检测结束")

        duration_col = QVBoxLayout()
        duration_col.setSpacing(2)
        duration_col.setContentsMargins(0, 0, 0, 0)
        duration_lbl = QLabel("检测天数")
        duration_lbl.setObjectName("dimLabel")
        self.txt_duration = QLineEdit()
        self.txt_duration.setReadOnly(True)
        self.txt_duration.setFocusPolicy(Qt.NoFocus)
        self.txt_duration.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        duration_col.addWidget(duration_lbl)
        duration_col.addWidget(self.txt_duration)

        date_layout.addLayout(col1, stretch=1)
        date_layout.addLayout(col2, stretch=1)
        date_layout.addLayout(col3, stretch=1)
        date_layout.addLayout(duration_col, stretch=1)
        info_layout.addWidget(date_bar)

        self._updating_dates = False
        self.date_receive.dateChanged.connect(self._on_dates_changed)
        self.date_start.dateChanged.connect(self._on_dates_changed)
        self.date_end.dateChanged.connect(self._on_dates_changed)
        self._on_dates_changed()

        left_layout.addWidget(info_group, stretch=2)

        # 2.2 Candidate pool — quotation / template switch
        pool_group = QGroupBox("候选池")
        pool_group.setObjectName("candidatePool")
        pool_layout = QVBoxLayout(pool_group)
        pool_layout.setContentsMargins(4, 6, 4, 4)
        pool_layout.setSpacing(4)

        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(4)
        self.btn_pool_quote = QPushButton("报价单")
        self.btn_pool_quote.setObjectName("poolToggle")
        self.btn_pool_quote.setCheckable(True)
        self.btn_pool_quote.setChecked(True)
        self.btn_pool_template = QPushButton("模板")
        self.btn_pool_template.setObjectName("poolToggle")
        self.btn_pool_template.setCheckable(True)
        self.pool_source = QButtonGroup(self)
        self.pool_source.setExclusive(True)
        self.pool_source.addButton(self.btn_pool_quote, 0)
        self.pool_source.addButton(self.btn_pool_template, 1)
        self.pool_source.idClicked.connect(self._refresh_pool_list)
        toggle_row.addWidget(self.btn_pool_quote, stretch=1)
        toggle_row.addWidget(self.btn_pool_template, stretch=1)
        pool_layout.addLayout(toggle_row)

        self.list_candidates = CandidatePoolList()
        pool_layout.addWidget(self.list_candidates)
        left_layout.addWidget(pool_group, stretch=1)

        # 2.3 Export — compact 2-row: mode+target | generate
        export_panel = QGroupBox("导出报告")
        export_panel.setObjectName("exportPanel")
        export_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        export_layout = QVBoxLayout(export_panel)
        export_layout.setContentsMargins(8, 6, 8, 6)
        export_layout.setSpacing(6)

        mode_target_row = QHBoxLayout()
        mode_target_row.setSpacing(6)
        self.combo_export_mode = QComboBox()
        self.combo_export_mode.addItems(["导出全部 Leg", "导出单条 Leg", "导出单项试验"])
        self.combo_export_mode.currentIndexChanged.connect(self._on_export_mode_changed)
        self.combo_export_mode.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_export_mode.setMinimumWidth(72)
        mode_target_row.addWidget(QLabel("导出模式:"))
        mode_target_row.addWidget(self.combo_export_mode, stretch=1)

        self.lbl_export_target = QLabel("导出目标:")
        self.combo_export_target = QComboBox()
        self.combo_export_target.setEnabled(False)
        self.combo_export_target.setPlaceholderText("全部 Leg")
        self.combo_export_target.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_export_target.setMinimumWidth(72)
        mode_target_row.addWidget(self.lbl_export_target)
        mode_target_row.addWidget(self.combo_export_target, stretch=1)
        export_layout.addLayout(mode_target_row)

        self.btn_export = QPushButton("一键生成报告")
        self.btn_export.setObjectName("primaryButton")
        self.btn_export.clicked.connect(self.export_report)
        export_layout.addWidget(self.btn_export)

        left_layout.addWidget(export_panel, stretch=0)

        splitter.addWidget(left_panel)

        self.right_panel = QGroupBox("Leg 图排布区")
        right_layout = QVBoxLayout(self.right_panel)
        self.leg_graph = LegGraphArea(self.state)
        self.leg_graph.btn_save.clicked.connect(self.save_state)
        self.leg_graph.btn_load_state.clicked.connect(self.load_saved_state)
        self.leg_graph.btn_save_template.clicked.connect(self.save_leg_template)
        self.leg_graph.btn_import_template.clicked.connect(self.import_leg_template)
        self.leg_graph.structure_changed.connect(self._on_structure_changed)
        right_layout.addWidget(self.leg_graph)
        splitter.addWidget(self.right_panel)

        # Left:right = 1:φ (golden ratio), locked on window resize
        self._main_splitter = splitter
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1000)
        splitter.setStretchFactor(1, 1618)
        handle = splitter.handle(1)
        if handle is not None:
            handle.setEnabled(False)
        self._apply_golden_split()
        main_layout.addWidget(splitter, stretch=1)

        self._on_export_mode_changed()

    def _apply_golden_split(self):
        splitter = getattr(self, "_main_splitter", None)
        if splitter is None:
            return
        total = splitter.size().width()
        if total <= 0:
            total = max(self.width(), 1)
        left = int(round(total / (1 + (1 + 5 ** 0.5) / 2)))
        splitter.setSizes([max(left, 1), max(total - left, 1)])

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_golden_split()
        self.list_candidates.fit_grid()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_golden_split()

    def closeEvent(self, event):
        if self._mirror_worker is not None:
            self._mirror_worker.requestInterruption()
            self._mirror_worker.wait(2000)
        for worker in list(self._abandoned_workers):
            worker.requestInterruption()
            worker.wait(500)
        super().closeEvent(event)

    # ---------- path helpers ----------

    @staticmethod
    def _normalize_path_input(raw):
        # type: (str) -> Optional[Path]
        text = (raw or "").strip().strip('"').strip("'")
        if not text:
            return None
        if text.startswith("file://"):
            parsed = urlparse(text)
            text = unquote(parsed.path)
        text = text.rstrip("/")
        path = Path(text).expanduser()
        try:
            path = path.resolve()
        except OSError:
            pass
        if path.exists() and path.is_dir():
            return path
        return None

    @staticmethod
    def _infer_project_id(folder: Path) -> str:
        name = folder.name
        m = re.search(r"(A\d{8,})", name, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        return name

    def browse_project_folder(self):
        start = str(self._source_path or self._project_path or Path("example").resolve())
        chosen = QFileDialog.getExistingDirectory(self, "选择项目文件夹", start)
        if not chosen:
            return
        self.txt_project_path.setText(chosen)
        self.load_project_folder(Path(chosen))

    def load_from_pasted_path(self):
        path = self._normalize_path_input(self.txt_project_path.text())
        if path is None or not path.is_dir():
            QMessageBox.warning(
                self, "路径无效",
                "请粘贴有效的项目文件夹路径，或使用「选择目录…」。",
            )
            return
        self.txt_project_path.setText(str(path))
        self.load_project_folder(path)

    # ---------- overview form ----------

    def _clear_info_form(self):
        while self.info_form.rowCount():
            self.info_form.removeRow(0)

    def _add_info_row(self, label: str, value: str):
        val = (value or "").strip()
        if not val:
            return
        key_lbl = QLabel(f"{label}:")
        key_lbl.setObjectName("dimLabel")
        key_lbl.setAlignment(Qt.AlignRight | Qt.AlignTop)

        row_w = QWidget()
        row_l = QHBoxLayout(row_w)
        row_l.setContentsMargins(0, 0, 0, 0)
        row_l.setSpacing(4)
        value_lbl = QLabel(val)
        value_lbl.setWordWrap(True)
        value_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        btn = QPushButton("✕")
        btn.setObjectName("fieldRemoveButton")
        btn.setFixedSize(20, 20)
        btn.setToolTip("移除此字段，生成报告时不再写入")
        btn.clicked.connect(lambda _checked=False, k=label: self._exclude_overview_field(k))
        row_l.addWidget(value_lbl, stretch=1)
        row_l.addWidget(btn, 0, Qt.AlignTop)
        self.info_form.addRow(key_lbl, row_w)

    def _exclude_overview_field(self, key: str):
        excluded = list(self.state.excluded_overview_keys or [])
        if key not in excluded:
            excluded.append(key)
            self.state.excluded_overview_keys = excluded
            self._mark_dirty()
        self.refresh_overview_ui()

    def refresh_overview_ui(self):
        self._clear_info_form()
        rows = list(self.state.iter_overview_fields())
        if not rows:
            hint = QLabel("未加载" if not self.state.application_fields else "暂无字段（已全部移除）")
            hint.setObjectName("dimLabel")
            self.info_form.addRow(hint)
        else:
            for k, v in rows:
                self._add_info_row(k, v)

        self.lbl_project_id.setText(f"项目号: {self.state.project_id or '—'}")
        self.lbl_project_id.setObjectName("dimLabel")
        self.lbl_project_id.style().unpolish(self.lbl_project_id)
        self.lbl_project_id.style().polish(self.lbl_project_id)

    def _fill_candidates(self, items: list):
        self.list_candidates.set_items(items)

    def _refresh_pool_list(self, *_args):
        if self.btn_pool_template.isChecked():
            self._fill_candidates(self.state.template_pool or [])
        else:
            self._fill_candidates(self.state.candidate_pool or [])

    # ---------- load ----------

    def load_project_folder(self, project_path: Path):
        if not project_path.is_dir():
            QMessageBox.warning(self, "错误", f"不是有效目录:\n{project_path}")
            return

        project_id = self._infer_project_id(project_path)
        local_path = local_project_dir(project_id)
        local_path.mkdir(parents=True, exist_ok=True)

        self._source_path = project_path
        self._local_path = local_path
        self._project_path = project_path
        self._mirror_ready = False

        self.state = ProjectState(
            project_id=project_id,
            source_path=str(project_path),
            project_path=str(local_path),
        )
        self.btn_pool_quote.setChecked(True)
        self.leg_graph.state = self.state
        self.leg_graph.reload_from_state()

        today = QDate.currentDate()
        self._updating_dates = True
        try:
            self.date_receive.setDate(today)
            self.date_start.setDate(today)
            self.date_end.setDate(today)
        finally:
            self._updating_dates = False
        self._on_dates_changed()

        self._parse_fresh_project(project_path)
        self.refresh_overview_ui()
        self._set_mirror_status("镜像中...", "dim")
        self._start_mirror(project_path, local_path)
        self._is_dirty = False
        self._on_export_mode_changed()

    def _parse_fresh_project(self, project_path):
        sample_dir = project_path / "1.接样组"
        app_excel = None
        quote_pdf = None

        if sample_dir.exists():
            for f in sample_dir.iterdir():
                if f.name.endswith(".xlsx") and not f.name.startswith("~"):
                    app_excel = f
                elif f.name.endswith(".pdf") and "报价单" in f.name:
                    quote_pdf = f

        if app_excel:
            try:
                raw = app_excel.read_bytes()
                clean, name = prepare_excel_bytes(raw, app_excel.name)
                data = parse_application(clean, name)

                self.state.applicant_name = data.applicant_name_cn or data.applicant_name
                self.state.applicant_address = data.applicant_address_cn or data.applicant_address
                self.state.report_title_name = data.report_title_name_cn or data.report_title_name_en
                self.state.report_title_address = (
                    data.report_title_address_cn or data.report_title_address_en
                )
                self.state.sample_name = data.sample_info.get("样品名称", "")

                fields = {}
                for k, v in (data.sample_info or {}).items():
                    if v is not None and str(v).strip():
                        fields[k] = str(v).strip()
                self.state.application_fields = fields
                self.refresh_overview_ui()
            except Exception as e:
                self._clear_info_form()
                self.info_form.addRow(QLabel(f"解析申请单失败: {e}"))
        else:
            self._clear_info_form()
            self.info_form.addRow(QLabel("未找到申请单 Excel"))

        self.list_candidates.clear()
        if quote_pdf:
            try:
                items = QuotationParser.extract_test_items(str(quote_pdf))
                items = [it for it in items if it != "服务项目Service Item"]
                self.state.candidate_pool = items
                self.btn_pool_quote.setChecked(True)
                self._refresh_pool_list()
                self.leg_graph.state = self.state
                self.leg_graph.notify_pool_changed()
            except Exception as e:
                self.list_candidates.set_items([f"解析报价单失败: {e}"])

        self.lbl_project_id.setText(f"项目号: {self.state.project_id}")
        self._on_export_mode_changed()

    # ---------- dates ----------

    def _sync_dates_to_state(self):
        self.state.sample_receive_date = self.date_receive.date().toString("yyyy-MM-dd")
        self.state.test_start_date = self.date_start.date().toString("yyyy-MM-dd")
        self.state.test_end_date = self.date_end.date().toString("yyyy-MM-dd")

    def _apply_date_string(self, date_edit, date_str):
        parsed = QDate.fromString(date_str or "", "yyyy-MM-dd")
        date_edit.setDate(parsed if parsed.isValid() else QDate.currentDate())

    def _apply_loaded_dates(self):
        self._updating_dates = True
        try:
            self._apply_date_string(self.date_receive, self.state.sample_receive_date)
            self._apply_date_string(self.date_start, self.state.test_start_date)
            self._apply_date_string(self.date_end, self.state.test_end_date)
        finally:
            self._updating_dates = False
        self._on_dates_changed()

    def _on_dates_changed(self, *_args):
        """receive ≤ start ≤ end."""
        if getattr(self, "_updating_dates", False):
            return
        self._updating_dates = True
        try:
            recv = self.date_receive.date()
            start = self.date_start.date()
            end = self.date_end.date()
            source = self.sender()

            unbounded_lo = QDate(1000, 1, 1)
            unbounded_hi = QDate(9999, 12, 31)
            for widget in (self.date_receive, self.date_start, self.date_end):
                widget.setMinimumDate(unbounded_lo)
                widget.setMaximumDate(unbounded_hi)

            if source is self.date_receive:
                if recv > start:
                    start = recv
                    self.date_start.setDate(start)
                if start > end:
                    end = start
                    self.date_end.setDate(end)
            elif source is self.date_start:
                if start < recv:
                    start = recv
                    self.date_start.setDate(start)
                if start > end:
                    end = start
                    self.date_end.setDate(end)
            elif source is self.date_end:
                if end < recv:
                    end = recv
                    self.date_end.setDate(end)
                if end < start:
                    start = end
                    if start < recv:
                        start = recv
                        end = recv
                        self.date_end.setDate(end)
                    self.date_start.setDate(start)
            else:
                if start < recv:
                    start = recv
                    self.date_start.setDate(start)
                if end < start:
                    end = start
                    self.date_end.setDate(end)

            self.date_start.setMinimumDate(recv)
            self.date_end.setMinimumDate(start)
            self._sync_dates_to_state()
            self._update_duration_display(start, end)
            if source in (self.date_receive, self.date_start, self.date_end):
                self._mark_dirty()
        finally:
            self._updating_dates = False

    def _update_duration_display(self, start, end):
        days = start.daysTo(end)
        self.txt_duration.setText(str(days))

    # ---------- export target UI ----------

    def _on_export_mode_changed(self):
        mode = self.combo_export_mode.currentText()
        self.combo_export_target.blockSignals(True)
        self.combo_export_target.clear()

        if mode == "导出全部 Leg":
            self.combo_export_target.setEnabled(False)
            self.combo_export_target.addItem("全部 Leg")
        elif mode == "导出单条 Leg":
            self.combo_export_target.setEnabled(True)
            legs = self.state.legs or []
            if not legs:
                self.combo_export_target.addItem("（当前无 Leg）")
                self.combo_export_target.setEnabled(False)
            else:
                for leg in legs:
                    node_names = [n.test_name for n in leg.nodes if n.test_name]
                    detail = " → ".join(node_names) if node_names else "（空）"
                    self.combo_export_target.addItem(
                        f"{leg.leg_name}  [{detail}]", userData=leg.leg_id
                    )
        else:  # 导出单项试验
            self.combo_export_target.setEnabled(True)
            found = False
            for leg in self.state.legs or []:
                for node in leg.nodes:
                    if not node.test_name:
                        continue
                    found = True
                    label = f"{leg.leg_name} / {node.test_name}"
                    self.combo_export_target.addItem(
                        label, userData=f"TEST:{leg.leg_name} - {node.test_name}"
                    )
            if not found:
                self.combo_export_target.addItem("（当前无试验）")
                self.combo_export_target.setEnabled(False)

        self.combo_export_target.blockSignals(False)

    # ---------- dirty / mirror helpers ----------

    def _mark_dirty(self):
        self._is_dirty = True

    def _on_structure_changed(self):
        self._mark_dirty()
        self._on_export_mode_changed()

    def _set_mirror_status(self, text, kind="dim"):
        names = {"dim": "dimLabel", "ok": "hintLabel", "err": "errorLabel"}
        self.lbl_mirror_status.setText(text or "")
        self.lbl_mirror_status.setObjectName(names.get(kind, "dimLabel"))
        self.lbl_mirror_status.style().unpolish(self.lbl_mirror_status)
        self.lbl_mirror_status.style().polish(self.lbl_mirror_status)

    def _drop_abandoned(self, worker):
        try:
            self._abandoned_workers.remove(worker)
        except ValueError:
            pass

    def _start_mirror(self, src, dest):
        if self._mirror_worker is not None:
            try:
                self._mirror_worker.succeeded.disconnect(self._on_mirror_ok)
                self._mirror_worker.failed.disconnect(self._on_mirror_fail)
            except (RuntimeError, TypeError):
                pass
            self._mirror_worker.requestInterruption()
            old = self._mirror_worker
            self._abandoned_workers.append(old)
            old.finished.connect(lambda _w=old: self._drop_abandoned(_w))
        self._mirror_gen += 1
        worker = MirrorWorker(src, dest, self._mirror_gen, self)
        worker.succeeded.connect(self._on_mirror_ok)
        worker.failed.connect(self._on_mirror_fail)
        self._mirror_worker = worker
        worker.start()

    def _on_mirror_ok(self, generation, dest):
        if generation != self._mirror_gen:
            return
        dest_path = Path(dest)
        if self._local_path is None or dest_path.resolve() != self._local_path.resolve():
            return
        self._mirror_ready = True
        self._project_path = self._local_path
        self.state.project_path = str(self._local_path)
        self._set_mirror_status("本地镜像完成", "ok")

    def _on_mirror_fail(self, generation, message):
        if generation != self._mirror_gen:
            return
        self._mirror_ready = False
        self._set_mirror_status(f"镜像失败: {message}", "err")

    def _confirm_discard_if_dirty(self):
        if not self._is_dirty:
            return True
        reply = QMessageBox.question(
            self,
            "未保存的修改",
            "当前修改未保存，是否放弃并加载？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _apply_state_to_ui(self):
        self._apply_loaded_dates()
        self.refresh_overview_ui()
        self.btn_pool_quote.setChecked(True)
        self._refresh_pool_list()
        self.leg_graph.state = self.state
        self.leg_graph.reload_from_state()
        self._on_export_mode_changed()

    # ---------- save / load state / export ----------

    def save_state(self):
        if not self.state.project_id:
            QMessageBox.warning(self, "提示", "请先加载项目")
            return
        self._sync_dates_to_state()
        if self._local_path is None:
            self._local_path = local_project_dir(self.state.project_id)
        self._local_path.mkdir(parents=True, exist_ok=True)
        self.state.project_path = str(self._local_path)
        save_path = self._local_path / "project_state.json"
        self.state.save_to_file(str(save_path))
        self._is_dirty = False
        QMessageBox.information(self, "已保存", f"项目已保存至:\n{save_path}")

    def load_saved_state(self):
        if not self._confirm_discard_if_dirty():
            return
        projects = list_saved_projects()
        if not projects:
            QMessageBox.information(self, "加载项目", "暂无已保存的项目")
            return
        dialog = LoadStateDialog(projects, self)
        if not dialog.exec():
            return
        saved = dialog.selected_project()
        if saved is None:
            return
        loaded = ProjectState.load_from_file(str(saved.json_path))
        loaded.project_id = loaded.project_id or saved.project_id
        loaded.project_path = str(saved.local_path)

        self.state = loaded
        self._local_path = saved.local_path
        self._project_path = saved.local_path
        self._source_path = Path(loaded.source_path) if loaded.source_path else saved.local_path
        self._mirror_ready = True
        self.txt_project_path.setText(loaded.source_path or str(saved.local_path))
        self._set_mirror_status("本地镜像完成", "ok")
        self._apply_state_to_ui()
        self._is_dirty = False

    def save_leg_template(self):
        if not self.state.project_id:
            QMessageBox.warning(self, "提示", "请先加载项目")
            return
        if not self.state.legs:
            QMessageBox.warning(self, "提示", "请先绘制 Leg 图")
            return
        name, ok = QInputDialog.getText(
            self,
            "保存为 Leg 模板",
            "模板名称:",
            text=self.state.last_leg_template_name or "",
        )
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, "提示", "模板名称不能为空")
            return
        try:
            path = write_leg_template(name, self.state.legs)
        except TemplateExistsError:
            reply = QMessageBox.question(
                self,
                "覆盖模板",
                f"已存在同名模板「{name}」，是否覆盖？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            path = write_leg_template(name, self.state.legs, overwrite=True)
        except TemplateNameError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self.state.last_leg_template_name = name
        self._mark_dirty()
        QMessageBox.information(self, "已保存", f"Leg 模板已保存至:\n{path}")

    def import_leg_template(self):
        if not self.state.project_id:
            QMessageBox.warning(self, "提示", "请先加载项目")
            return
        templates = list_leg_templates()
        if not templates:
            QMessageBox.information(self, "导入模板", "暂无已保存的 Leg 模板")
            return
        dialog = ImportTemplateDialog(templates, self)
        if not dialog.exec():
            return
        saved = dialog.selected_template()
        if saved is None:
            return
        if self.state.legs:
            reply = QMessageBox.question(
                self,
                "覆盖 Leg 图",
                "导入将覆盖当前 Leg 图，是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        try:
            name, legs = read_leg_template(saved.json_path)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", f"无法读取模板:\n{exc}")
            return
        apply_leg_template(self.state, name, legs)
        self.btn_pool_template.setChecked(True)
        self._refresh_pool_list()
        self.leg_graph.state = self.state
        self.leg_graph.reload_from_state()
        self.leg_graph.notify_pool_changed()
        self._mark_dirty()

    def export_report(self):
        if not self.state.project_id:
            QMessageBox.warning(self, "错误", "请先加载项目！")
            return
        if not self._mirror_ready or self._local_path is None or not self._local_path.is_dir():
            QMessageBox.warning(self, "提示", "本地镜像尚未完成，请稍候")
            return

        try:
            from src.generators.word_engine import WordGenerator

            template_path = Path("templates/template_raw.docx")
            if not template_path.exists():
                QMessageBox.warning(self, "错误", f"找不到模板文件: {template_path}")
                return

            out_name = f"{self.state.project_id}_Report.docx"
            project_path = self._local_path

            if project_path and project_path.is_dir():
                report_dir = project_path / "4.报告组"
                report_dir.mkdir(exist_ok=True)
                out_path = report_dir / out_name
            else:
                out_path = Path(".scratch") / out_name

            engine = WordGenerator(str(template_path))
            mode = self.combo_export_mode.currentText()
            target_project_path = str(project_path) if project_path else None
            target_text = self.combo_export_target.currentText()

            if mode == "导出单条 Leg":
                leg_id = self.combo_export_target.currentData()
                if not leg_id:
                    QMessageBox.warning(self, "错误", "请先选择要导出的 Leg")
                    return
                engine.generate(
                    self.state, str(out_path),
                    project_path=target_project_path, leg_filter=leg_id,
                )
                scope_note = f"\n导出范围: Leg → {target_text}"
            elif mode == "导出单项试验":
                test_key = self.combo_export_target.currentData()
                if not test_key:
                    QMessageBox.warning(self, "错误", "请先选择要导出的试验")
                    return
                engine.generate(
                    self.state, str(out_path),
                    project_path=target_project_path, leg_filter=test_key,
                )
                scope_note = f"\n导出范围: 试验 → {target_text}"
            else:
                engine.generate(
                    self.state, str(out_path), project_path=target_project_path
                )
                scope_note = "\n导出范围: 全部 Leg"

            msg = QMessageBox(self)
            msg.setWindowTitle("导出成功")
            msg.setText(f"报告已生成至:\n{out_path}{scope_note}")
            btn_open = msg.addButton("打开所在文件夹", QMessageBox.ActionRole)
            msg.addButton(QMessageBox.Ok)
            msg.exec()

            if msg.clickedButton() == btn_open:
                subprocess.run(["open", "-R", str(out_path)])

        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"生成报告时发生错误:\n{str(e)}")


if __name__ == "__main__":
    from src.ui.theme import apply_cyberpunk_theme
    app = QApplication(sys.argv)
    apply_cyberpunk_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
