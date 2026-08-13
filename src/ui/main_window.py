import sys
import re
import subprocess
from typing import Optional
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QListWidget, QListView, QGroupBox, QSplitter,
    QComboBox, QMessageBox, QDateEdit, QFileDialog, QFormLayout, QScrollArea,
    QSizePolicy, QFrame,
)
from PySide6.QtCore import Qt, QDate, QSize

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.models.project_state import ProjectState
from application_parser import parse_application, prepare_excel_bytes
from src.parsers.pdf_parser import QuotationParser
from src.ui.leg_graph import LegGraphArea


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Report Creator")
        self.resize(1100, 750)
        self.state = ProjectState()
        self._project_path = None  # type: Optional[Path]

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

        self.lbl_project_id = QLabel("项目号: —")
        self.lbl_project_id.setObjectName("dimLabel")
        top_outer.addWidget(self.lbl_project_id)

        main_layout.addWidget(top_panel)

        splitter = QSplitter(Qt.Horizontal)

        # 2. Left Panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 2.1 Project overview — all homepage fields
        info_group = QGroupBox("项目概况")
        info_layout = QVBoxLayout(info_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(220)
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
        info_layout.addWidget(scroll)

        date_layout = QVBoxLayout()

        def make_date_row(label_text):
            row_l = QHBoxLayout()
            lbl = QLabel(label_text)
            date_edit = QDateEdit()
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("yyyy-MM-dd")
            date_edit.setDate(QDate.currentDate())
            date_edit.lineEdit().setReadOnly(True)
            row_l.addWidget(lbl)
            row_l.addWidget(date_edit)
            return row_l, date_edit

        row1, self.date_receive = make_date_row("接收日期:")
        row2, self.date_start = make_date_row("检测开始:")
        row3, self.date_end = make_date_row("检测结束:")
        date_layout.addLayout(row1)
        date_layout.addLayout(row2)
        date_layout.addLayout(row3)
        info_layout.addLayout(date_layout)

        self.date_receive.dateChanged.connect(
            lambda d: setattr(self.state, "sample_receive_date", d.toString("yyyy-MM-dd"))
        )
        self.date_start.dateChanged.connect(
            lambda d: setattr(self.state, "test_start_date", d.toString("yyyy-MM-dd"))
        )
        self.date_end.dateChanged.connect(
            lambda d: setattr(self.state, "test_end_date", d.toString("yyyy-MM-dd"))
        )
        self._sync_dates_to_state()

        left_layout.addWidget(info_group, stretch=3)

        # 2.2 Candidate pool — multi-column wrapping
        pool_group = QGroupBox("项目候选池 (从报价单提取)")
        pool_layout = QVBoxLayout(pool_group)
        self.list_candidates = QListWidget()
        self.list_candidates.setFlow(QListView.LeftToRight)
        self.list_candidates.setWrapping(True)
        self.list_candidates.setResizeMode(QListView.Adjust)
        self.list_candidates.setMovement(QListView.Static)
        self.list_candidates.setSpacing(4)
        self.list_candidates.setWordWrap(True)
        self.list_candidates.setGridSize(QSize(150, 28))
        # Force multi-column wrapping layout
        self.list_candidates.setViewMode(QListView.IconMode)
        self.list_candidates.setUniformItemSizes(True)
        pool_layout.addWidget(self.list_candidates)
        left_layout.addWidget(pool_group, stretch=2)

        # 2.3 Export — target visible before generate
        export_panel = QGroupBox("导出报告")
        export_layout = QVBoxLayout(export_panel)
        export_layout.setSpacing(6)

        mode_row = QHBoxLayout()
        self.combo_export_mode = QComboBox()
        self.combo_export_mode.addItems(["导出全部 Leg", "导出单条 Leg", "导出单项试验"])
        self.combo_export_mode.currentIndexChanged.connect(self._on_export_mode_changed)
        mode_row.addWidget(QLabel("导出模式:"))
        mode_row.addWidget(self.combo_export_mode, stretch=1)
        export_layout.addLayout(mode_row)

        target_row = QHBoxLayout()
        self.lbl_export_target = QLabel("导出目标:")
        self.combo_export_target = QComboBox()
        self.combo_export_target.setEnabled(False)
        self.combo_export_target.setPlaceholderText("全部 Leg")
        target_row.addWidget(self.lbl_export_target)
        target_row.addWidget(self.combo_export_target, stretch=1)
        export_layout.addLayout(target_row)

        self.lbl_export_hint = QLabel("当前将导出: 全部 Leg")
        self.lbl_export_hint.setWordWrap(True)
        self.lbl_export_hint.setObjectName("hintLabel")
        export_layout.addWidget(self.lbl_export_hint)
        self.combo_export_target.currentTextChanged.connect(self._refresh_export_hint)

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
        self.leg_graph.structure_changed.connect(self._on_export_mode_changed)
        right_layout.addWidget(self.leg_graph)
        splitter.addWidget(self.right_panel)

        splitter.setSizes([320, 780])
        main_layout.addWidget(splitter, stretch=1)

        self._on_export_mode_changed()

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
        start = str(self._project_path or Path("example").resolve())
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
        value_lbl = QLabel(val)
        value_lbl.setWordWrap(True)
        value_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info_form.addRow(key_lbl, value_lbl)

    def refresh_overview_ui(self):
        self._clear_info_form()
        fields = dict(self.state.application_fields or {})

        # Prefer structured applicant / title fields at top if present
        ordered_head = []
        for key, attr in (
            ("申请公司", "applicant_name"),
            ("申请公司地址", "applicant_address"),
            ("报告抬头公司", "report_title_name"),
            ("报告抬头地址", "report_title_address"),
        ):
            val = getattr(self.state, attr, "") or fields.pop(key, "")
            if val:
                ordered_head.append((key, val))

        # sample_name convenience
        if self.state.sample_name and "样品名称" not in fields:
            fields = {"样品名称": self.state.sample_name, **fields}

        if not ordered_head and not fields:
            self.info_form.addRow(QLabel("未加载"))
            return

        for k, v in ordered_head:
            self._add_info_row(k, v)
        for k, v in fields.items():
            if k in {"申请公司", "申请公司地址", "报告抬头公司", "报告抬头地址"}:
                continue
            self._add_info_row(k, v)

        self.lbl_project_id.setText(
            f"项目号: {self.state.project_id or '—'}  ·  {self.state.project_path or ''}"
        )
        self.lbl_project_id.setObjectName("dimLabel")
        self.lbl_project_id.style().unpolish(self.lbl_project_id)
        self.lbl_project_id.style().polish(self.lbl_project_id)

    def _fill_candidates(self, items: list):
        self.list_candidates.clear()
        self.list_candidates.addItems(items)
        # Widen grid cells a bit for longer names
        if items:
            longest = max(len(i) for i in items)
            w = max(120, min(200, longest * 8))
            self.list_candidates.setGridSize(QSize(w, 36))

    # ---------- load ----------

    def load_project_folder(self, project_path: Path):
        if not project_path.is_dir():
            QMessageBox.warning(self, "错误", f"不是有效目录:\n{project_path}")
            return

        project_id = self._infer_project_id(project_path)
        self._project_path = project_path
        self.state.project_id = project_id
        self.state.project_path = str(project_path)

        local_state_path = Path(f".scratch/{project_id}_state.json")
        if local_state_path.exists():
            loaded = ProjectState.load_from_file(str(local_state_path))
            self.state = loaded
            self.state.project_path = str(project_path)
            self.state.project_id = project_id or self.state.project_id

            self._apply_date_string(self.date_receive, self.state.sample_receive_date)
            self._apply_date_string(self.date_start, self.state.test_start_date)
            self._apply_date_string(self.date_end, self.state.test_end_date)
            self._sync_dates_to_state()

            # 旧存档可能没有 application_fields，补解析申请单首页字段
            if not self.state.application_fields:
                self._backfill_application_fields(project_path)

            self.refresh_overview_ui()
            self._fill_candidates(self.state.candidate_pool)
            self.leg_graph.state = self.state
            self.leg_graph.reload_from_state()
            self._on_export_mode_changed()
            return

        self._parse_fresh_project(project_path)

    def _backfill_application_fields(self, project_path):
        sample_dir = project_path / "1.接样组"
        if not sample_dir.exists():
            return
        app_excel = None
        for f in sample_dir.iterdir():
            if f.name.endswith(".xlsx") and not f.name.startswith("~"):
                app_excel = f
                break
        if not app_excel:
            return
        try:
            raw = app_excel.read_bytes()
            clean, name = prepare_excel_bytes(raw, app_excel.name)
            data = parse_application(clean, name)
            if not self.state.applicant_name:
                self.state.applicant_name = data.applicant_name_cn or data.applicant_name
            if not self.state.applicant_address:
                self.state.applicant_address = data.applicant_address_cn or data.applicant_address
            if not self.state.report_title_name:
                self.state.report_title_name = data.report_title_name_cn or data.report_title_name_en
            if not self.state.report_title_address:
                self.state.report_title_address = (
                    data.report_title_address_cn or data.report_title_address_en
                )
            if not self.state.sample_name:
                self.state.sample_name = data.sample_info.get("样品名称", "")
            fields = {}
            for k, v in (data.sample_info or {}).items():
                if v is not None and str(v).strip():
                    fields[k] = str(v).strip()
            self.state.application_fields = fields
        except Exception:
            pass

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

                # Keep every non-empty field from the application (homepage)
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
                self._fill_candidates(items)
                self.leg_graph.state = self.state
                self.leg_graph.notify_pool_changed()
            except Exception as e:
                self.list_candidates.addItem(f"解析报价单失败: {e}")

        self.lbl_project_id.setText(
            f"项目号: {self.state.project_id}  ·  {project_path}"
        )
        self._on_export_mode_changed()

    # ---------- dates ----------

    def _sync_dates_to_state(self):
        self.state.sample_receive_date = self.date_receive.date().toString("yyyy-MM-dd")
        self.state.test_start_date = self.date_start.date().toString("yyyy-MM-dd")
        self.state.test_end_date = self.date_end.date().toString("yyyy-MM-dd")

    def _apply_date_string(self, date_edit, date_str):
        parsed = QDate.fromString(date_str or "", "yyyy-MM-dd")
        date_edit.setDate(parsed if parsed.isValid() else QDate.currentDate())

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
        self._refresh_export_hint()

    def _refresh_export_hint(self):
        mode = self.combo_export_mode.currentText()
        target = self.combo_export_target.currentText()
        if mode == "导出全部 Leg":
            self.lbl_export_hint.setText("当前将导出: 全部 Leg")
        elif mode == "导出单条 Leg":
            self.lbl_export_hint.setText(f"当前将导出 Leg: {target}")
        else:
            self.lbl_export_hint.setText(f"当前将导出试验: {target}")

    # ---------- save / export ----------

    def save_state(self):
        if not self.state.project_id:
            QMessageBox.warning(self, "提示", "请先加载项目")
            return
        save_path = f".scratch/{self.state.project_id}_state.json"
        self.state.save_to_file(save_path)
        QMessageBox.information(self, "已保存", f"状态已保存至:\n{save_path}")

    def export_report(self):
        if not self.state.project_id:
            QMessageBox.warning(self, "错误", "请先加载项目！")
            return

        try:
            from src.generators.word_engine import WordGenerator

            template_path = Path("templates/template_raw.docx")
            if not template_path.exists():
                QMessageBox.warning(self, "错误", f"找不到模板文件: {template_path}")
                return

            out_name = f"{self.state.project_id}_Report.docx"
            project_path = self._project_path
            if project_path is None and self.state.project_path:
                project_path = Path(self.state.project_path)

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
