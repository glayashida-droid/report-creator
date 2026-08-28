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
    QInputDialog, QButtonGroup, QToolButton, QDialog,
)
from PySide6.QtCore import Qt, QDate, QThread, Signal, QEvent, QObject, QSize

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.models.project_state import ProjectState
from src.ui.test_photos_panel import warn_duplicate_test_names
from src.application_ingest import apply_application_data
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
from src.parsers.db_loader import DuplicateStandardError, duplicate_standard_message
from src.ui.leg_graph import LegGraphArea
from src.ui.load_state_dialog import LoadStateDialog
from src.ui.leg_template_dialog import ImportTemplateDialog
from src.ui.save_success_dialog import SaveSuccessDialog
from src.ui.candidate_pool import CandidatePoolList
from src.ui.theme import polish_date_edit_calendar, refresh_icon, set_calendar_selectable_range
from src.language_copy import field_label


class _GroupTitleButtonHost(QObject):
    """Keep a small tool button parked just right of a QGroupBox title."""

    def __init__(self, group: QGroupBox, button: QToolButton, parent=None):
        super().__init__(parent)
        self._group = group
        self._button = button
        group.installEventFilter(self)
        self.reposition()

    def eventFilter(self, watched, event):
        if watched is self._group and event.type() in (
            QEvent.Resize,
            QEvent.Show,
            QEvent.LayoutRequest,
        ):
            self.reposition()
        return False

    def reposition(self):
        group = self._group
        btn = self._button
        btn.adjustSize()
        fm = group.fontMetrics()
        # Match QGroupBox::title QSS: left 12px, horizontal padding 8px
        x = 12 + 8 + fm.horizontalAdvance(group.title()) + 2
        y = max(0, (14 - btn.height()) // 2 + 1)
        btn.move(x, y)
        btn.raise_()


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


APP_VERSION = "1.2.3"
# Calendar popup floor. Dates before this are treated as "no end date"
# because QDateEdit may clamp the blank sentinel to 1752-09-14.
_EARLIEST_REAL_YEAR = 1990


def _is_blank_project_date(value: QDate) -> bool:
    return (not value.isValid()) or value.year() < _EARLIEST_REAL_YEAR


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
        row.setAlignment(Qt.AlignVCenter)
        self.txt_project_path = QLineEdit()
        self.txt_project_path.setObjectName("projectPathInput")
        self.txt_project_path.setPlaceholderText(
            "粘贴项目文件夹路径 / 链接，或点击「选择项目」"
        )
        self.txt_project_path.returnPressed.connect(self.load_from_pasted_path)

        self.btn_edit_lang = QPushButton("中/英")
        self.btn_edit_lang.setObjectName("poolToggle")
        self.btn_edit_lang.setCheckable(True)
        self.btn_edit_lang.setChecked(True)
        self.btn_edit_lang.setFixedWidth(52)
        self.btn_edit_lang.setToolTip("点击切换编辑语言")
        self.btn_edit_lang.clicked.connect(self._toggle_edit_language)

        # Same objectName/style as language toggle so heights match exactly
        btn_load = QPushButton("从路径加载项目")
        btn_load.setObjectName("poolToggle")
        btn_load.setFixedWidth(128)
        btn_load.clicked.connect(self.load_from_pasted_path)

        btn_browse = QPushButton("选择项目")
        btn_browse.setObjectName("poolToggle")
        btn_browse.setProperty("accent", True)
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self.browse_project_folder)
        # Refresh style so [accent="true"] selector applies
        btn_browse.style().unpolish(btn_browse)
        btn_browse.style().polish(btn_browse)

        row.addWidget(QLabel("路径:"))
        row.addWidget(self.txt_project_path, stretch=1)
        row.addWidget(btn_load)
        row.addWidget(btn_browse)
        row.addWidget(self.btn_edit_lang)
        top_outer.addLayout(row)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        self.lbl_project_id = QLabel("项目号: —")
        self.lbl_project_id.setObjectName("dimLabel")
        self.lbl_mirror_status = QLabel("")
        self.lbl_mirror_status.setObjectName("dimLabel")
        self.btn_open_local = QPushButton("打开")
        self.btn_open_local.setObjectName("mirrorOpenLink")
        self.btn_open_local.setFlat(True)
        self.btn_open_local.setCursor(Qt.PointingHandCursor)
        self.btn_open_local.setVisible(False)
        self.btn_open_local.setToolTip("在访达中打开本地镜像文件夹")
        self.btn_open_local.clicked.connect(self._open_local_project_folder)
        mirror_row = QHBoxLayout()
        mirror_row.setContentsMargins(0, 0, 0, 0)
        mirror_row.setSpacing(4)
        mirror_row.addWidget(self.lbl_mirror_status)
        mirror_row.addWidget(self.btn_open_local)
        meta_row.addWidget(self.lbl_project_id)
        meta_row.addStretch()
        meta_row.addLayout(mirror_row)
        top_outer.addLayout(meta_row)

        main_layout.addWidget(top_panel)

        splitter = QSplitter(Qt.Horizontal)

        # 2. Left Panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 2.1 Project overview — all homepage fields
        info_group = QGroupBox("项目信息")
        info_group.setObjectName("overviewGroup")
        self._info_group = info_group
        info_layout = QVBoxLayout(info_group)
        info_layout.setContentsMargins(10, 16, 10, 8)
        info_layout.setSpacing(6)

        self.btn_reload_info = QToolButton(info_group)
        self.btn_reload_info.setObjectName("overviewReload")
        self.btn_reload_info.setIcon(refresh_icon(size=12))
        self.btn_reload_info.setIconSize(QSize(12, 12))
        self.btn_reload_info.setText("Reload")
        self.btn_reload_info.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_reload_info.setAutoRaise(True)
        self.btn_reload_info.setFixedHeight(16)
        self.btn_reload_info.adjustSize()
        self.btn_reload_info.setCursor(Qt.PointingHandCursor)
        self.btn_reload_info.setToolTip("重载申请单")
        self.btn_reload_info.clicked.connect(self.restore_excluded_overview_fields)
        self._info_reload_host = _GroupTitleButtonHost(info_group, self.btn_reload_info, self)

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
        self.info_form.setVerticalSpacing(2)
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

        def make_date_column(label_key):
            col = QVBoxLayout()
            col.setSpacing(2)
            col.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(field_label(label_key, "中文") or label_key)
            lbl.setObjectName("dimLabel")
            lbl.setAlignment(Qt.AlignHCenter)
            date_edit = QDateEdit()
            date_edit.setCalendarPopup(True)
            # Match report / 申请单 sample-info date writing (YYYY.MM.DD)
            date_edit.setDisplayFormat("yyyy.MM.dd")
            date_edit.lineEdit().setReadOnly(True)
            self._configure_optional_date(date_edit)
            col.addWidget(lbl)
            col.addWidget(date_edit)
            return col, date_edit, lbl

        col1, self.date_receive, self.lbl_date_receive = make_date_column("样品接收日期")
        col2, self.date_start, self.lbl_date_start = make_date_column("检测开始")
        col3, self.date_end, self.lbl_date_end = make_date_column("检测结束")

        duration_col = QVBoxLayout()
        duration_col.setSpacing(2)
        duration_col.setContentsMargins(0, 0, 0, 0)
        self.lbl_date_duration = QLabel(field_label("检测天数", "中文") or "天数")
        self.lbl_date_duration.setObjectName("dimLabel")
        self.lbl_date_duration.setAlignment(Qt.AlignHCenter)
        self.txt_duration = QLineEdit()
        self.txt_duration.setObjectName("durationDays")
        self.txt_duration.setReadOnly(True)
        self.txt_duration.setFocusPolicy(Qt.NoFocus)
        self.txt_duration.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        # Fixed narrow box: don't share stretch with date columns (avoids clip / long empty bar)
        self.txt_duration.setFixedWidth(56)
        self.txt_duration.setFixedHeight(self.date_receive.sizeHint().height())
        duration_col.addWidget(self.lbl_date_duration)
        duration_col.addWidget(self.txt_duration)

        date_layout.addLayout(col1, stretch=1)
        date_layout.addLayout(col2, stretch=1)
        date_layout.addLayout(col3, stretch=1)
        date_layout.addLayout(duration_col, stretch=0)
        info_layout.addWidget(date_bar)

        self._updating_dates = False
        self.date_receive.dateChanged.connect(self._on_dates_changed)
        self.date_start.dateChanged.connect(self._on_dates_changed)
        self.date_end.dateChanged.connect(self._on_dates_changed)
        self._install_calendar_bounds_on_show()
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

        # 2.3 Export — single row: mode + target + generate
        export_panel = QGroupBox("导出报告")
        export_panel.setObjectName("exportPanel")
        export_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        export_layout = QVBoxLayout(export_panel)
        export_layout.setContentsMargins(8, 6, 8, 6)
        export_layout.setSpacing(6)

        export_row = QHBoxLayout()
        export_row.setSpacing(6)
        self.combo_export_mode = QComboBox()
        self.combo_export_mode.addItems(["全部 Leg", "单条 Leg", "单项试验"])
        self.combo_export_mode.currentIndexChanged.connect(self._on_export_mode_changed)
        self.combo_export_mode.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_export_mode.setMinimumWidth(72)
        export_row.addWidget(QLabel("导出模式:"))
        export_row.addWidget(self.combo_export_mode, stretch=1)

        self.lbl_export_target = QLabel("导出目标:")
        self.combo_export_target = QComboBox()
        self.combo_export_target.setEnabled(False)
        self.combo_export_target.setPlaceholderText("全部 Leg")
        self.combo_export_target.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_export_target.setMinimumWidth(56)
        export_row.addWidget(self.lbl_export_target)
        export_row.addWidget(self.combo_export_target, stretch=1)

        self.btn_export = QPushButton("生成")
        self.btn_export.setObjectName("primaryButton")
        self.btn_export.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.btn_export.clicked.connect(self.export_report)
        export_row.addWidget(self.btn_export)
        export_layout.addLayout(export_row)

        left_layout.addWidget(export_panel, stretch=0)

        splitter.addWidget(left_panel)

        self.right_panel = QGroupBox("项目明细")
        right_layout = QVBoxLayout(self.right_panel)
        self.leg_graph = LegGraphArea(self.state)
        # clicked(bool) must not map to save_state(show_success=…)
        self.leg_graph.btn_save.clicked.connect(lambda: self.save_state())
        self.leg_graph.btn_load_state.clicked.connect(self.load_saved_state)
        self.leg_graph.btn_save_template.clicked.connect(self.save_leg_template)
        self.leg_graph.btn_import_template.clicked.connect(self.import_leg_template)
        self.leg_graph.structure_changed.connect(self._on_structure_changed)
        right_layout.addWidget(self.leg_graph, stretch=1)
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

    def _confirm_unsaved_exit(self):
        """Ask how to leave with unsaved work. Returns 'exit', 'save', or 'back'."""
        dlg = QDialog(self)
        dlg.setWindowTitle("提示")
        dlg.setModal(True)
        root = QVBoxLayout(dlg)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(16)
        root.addWidget(QLabel("项目未保存，是否退出"))

        row = QHBoxLayout()
        row.setSpacing(12)
        btn_exit = QPushButton("直接退出")
        btn_back = QPushButton("返回")
        btn_save = QPushButton("保存并退出")
        btn_save.setObjectName("accentButton")
        for btn in (btn_exit, btn_back, btn_save):
            btn.setMinimumWidth(110)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            row.addWidget(btn)
        root.addLayout(row)

        choice = {"value": "back"}

        def _pick(value):
            choice["value"] = value
            dlg.accept()

        btn_exit.clicked.connect(lambda: _pick("exit"))
        btn_back.clicked.connect(lambda: _pick("back"))
        btn_save.clicked.connect(lambda: _pick("save"))
        btn_back.setDefault(True)
        btn_back.setFocus()
        dlg.exec()
        return choice["value"]

    def closeEvent(self, event):
        if self._has_unsaved_changes():
            choice = self._confirm_unsaved_exit()
            if choice == "back":
                event.ignore()
                return
            if choice == "save":
                if not self.save_state(show_success=False):
                    event.ignore()
                    return

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
        self._set_path_text(chosen)
        self.load_project_folder(Path(chosen))

    def _set_path_text(self, text: str):
        """Set path line edit and keep the start of long paths visible."""
        self.txt_project_path.setText(text or "")
        self.txt_project_path.setCursorPosition(0)

    def load_from_pasted_path(self):
        path = self._normalize_path_input(self.txt_project_path.text())
        if path is None or not path.is_dir():
            QMessageBox.warning(
                self, "路径无效",
                "请粘贴有效的项目文件夹路径，或使用「选择项目」。",
            )
            return
        self._set_path_text(str(path))
        self.load_project_folder(path)

    def restore_excluded_overview_fields(self):
        """Show overview fields again after ✕ removals (no re-parse)."""
        if not (self.state.application_fields or self.state.project_id):
            QMessageBox.warning(self, "提示", "请先加载项目")
            return
        if not self.state.excluded_overview_keys:
            return
        self.state.excluded_overview_keys = []
        self.refresh_overview_ui()
        self._mark_dirty()

    # ---------- overview form ----------

    def _clear_info_form(self):
        while self.info_form.rowCount():
            self.info_form.removeRow(0)

    def _add_info_row(self, key: str, value: str, *, display_label: Optional[str] = None):
        # Internal key stays Chinese; left text follows edit_language (same FIELD_LABELS as export).
        caption = (display_label if display_label is not None else key) or key
        key_lbl = QLabel(f"{caption}:")
        key_lbl.setObjectName("dimLabel")
        key_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        row_w = QWidget()
        row_l = QHBoxLayout(row_w)
        row_l.setContentsMargins(0, 0, 0, 0)
        row_l.setSpacing(4)
        edit = QLineEdit(value or "")
        edit.setCursorPosition(0)  # show start of long values, not the tail
        edit.setPlaceholderText("（空）" if self.state._edit_lang() == "英文" else "")
        edit.editingFinished.connect(
            lambda k=key, w=edit: self._on_overview_field_edited(k, w)
        )
        btn = QPushButton("✕")
        btn.setObjectName("fieldRemoveButton")
        btn.setFixedSize(20, 20)
        btn.setToolTip("移除此字段，生成报告时不再写入")
        btn.clicked.connect(lambda _checked=False, k=key: self._exclude_overview_field(k))
        row_l.addWidget(edit, stretch=1)
        row_l.addWidget(btn, 0, Qt.AlignVCenter)
        self.info_form.addRow(key_lbl, row_w)

    def _sync_date_bar_labels(self):
        lang = self.state._edit_lang()
        self.lbl_date_receive.setText(
            field_label("样品接收日期", lang) or "样品接收日期"
        )
        self.lbl_date_start.setText(field_label("检测开始", lang) or "试验开始")
        self.lbl_date_end.setText(field_label("检测结束", lang) or "试验结束")
        self.lbl_date_duration.setText(field_label("检测天数", lang) or "天数")

    def _on_overview_field_edited(self, key: str, edit: QLineEdit):
        self.state.set_overview_value(key, edit.text())
        self._mark_dirty()

    def _toggle_edit_language(self):
        # Keep poolToggle:checked styling; Qt would otherwise uncheck on click.
        self.btn_edit_lang.setChecked(True)
        next_lang = "英文" if self.state._edit_lang() != "英文" else "中文"
        self.state.edit_language = next_lang
        self.refresh_overview_ui()

    def _sync_edit_language_buttons(self):
        lang = self.state._edit_lang()
        self.btn_edit_lang.blockSignals(True)
        self.btn_edit_lang.setText("中/英")
        self.btn_edit_lang.setToolTip(f"当前：{lang}（点击切换）")
        self.btn_edit_lang.setChecked(True)
        self.btn_edit_lang.blockSignals(False)

    def _exclude_overview_field(self, key: str):
        excluded = list(self.state.excluded_overview_keys or [])
        if key not in excluded:
            excluded.append(key)
            self.state.excluded_overview_keys = excluded
            self._mark_dirty()
        self.refresh_overview_ui()

    def refresh_overview_ui(self):
        self._sync_edit_language_buttons()
        self._sync_date_bar_labels()
        self._clear_info_form()
        rows = list(self.state.iter_overview_fields())
        has_fields = bool(self.state.application_fields or self.state.application_fields_en)
        lang = self.state._edit_lang()
        if not rows:
            hint = QLabel("未加载" if not has_fields else "暂无字段（已全部移除）")
            hint.setObjectName("dimLabel")
            self.info_form.addRow(hint)
        else:
            for k, v in rows:
                caption = field_label(k, lang) or k
                self._add_info_row(k, v, display_label=caption)

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

        self._updating_dates = True
        try:
            self._clear_date(self.date_receive)
            self._clear_date(self.date_start)
            self._clear_date(self.date_end)
        finally:
            self._updating_dates = False
        self._on_dates_changed()

        self._parse_fresh_project(project_path)
        self.refresh_overview_ui()
        self._set_mirror_status("镜像中...", "dim")
        self._start_mirror(project_path, local_path)
        self._is_dirty = False
        self._on_export_mode_changed()

    def _find_sample_files(self, project_path: Path):
        """Locate 申请单 Excel and 报价单 PDF under 1.接样组."""
        sample_dir = Path(project_path) / "1.接样组"
        app_excel = None
        quote_pdf = None
        if sample_dir.exists():
            for f in sample_dir.iterdir():
                if f.name.endswith(".xlsx") and not f.name.startswith("~"):
                    app_excel = f
                elif f.name.endswith(".pdf") and "报价单" in f.name:
                    quote_pdf = f
        return app_excel, quote_pdf

    def _parse_application_only(self, project_path: Path) -> bool:
        """Parse 申请单 into left-panel overview fields. Returns True on success."""
        app_excel, _quote_pdf = self._find_sample_files(project_path)
        if not app_excel:
            self._clear_info_form()
            self.info_form.addRow(QLabel("未找到申请单 Excel"))
            self.lbl_project_id.setText(f"项目号: {self.state.project_id or '—'}")
            return False
        try:
            raw = app_excel.read_bytes()
            clean, name = prepare_excel_bytes(raw, app_excel.name)
            data = parse_application(clean, name)
            apply_application_data(self.state, data)
            self.refresh_overview_ui()
            return True
        except Exception as e:
            self._clear_info_form()
            self.info_form.addRow(QLabel(f"解析申请单失败: {e}"))
            self.lbl_project_id.setText(f"项目号: {self.state.project_id or '—'}")
            return False

    def _parse_fresh_project(self, project_path):
        self._parse_application_only(project_path)

        _app_excel, quote_pdf = self._find_sample_files(project_path)
        self.list_candidates.clear()
        if quote_pdf:
            try:
                items = QuotationParser.extract_test_items(str(quote_pdf))
                self.state.candidate_pool = items
                self.btn_pool_quote.setChecked(True)
                self._refresh_pool_list()
                self.leg_graph.state = self.state
                self.leg_graph.notify_pool_changed()
            except Exception as e:
                self.list_candidates.set_items([f"解析报价单失败: {e}"])

        self.lbl_project_id.setText(f"项目号: {self.state.project_id}")
        self._on_export_mode_changed()

    def _install_calendar_bounds_on_show(self):
        """Re-apply selectable range whenever a calendar popup opens."""
        from PySide6.QtCore import QEvent, QObject

        class _BoundsFilter(QObject):
            def __init__(self, window):
                super().__init__(window)
                self._window = window

            def eventFilter(self, obj, event):
                if event.type() == QEvent.Show:
                    self._window._refresh_date_calendar_bounds()
                return False

        filt = _BoundsFilter(self)
        self._calendar_bounds_filter = filt
        for date_edit in (self.date_receive, self.date_start, self.date_end):
            calendar = date_edit.calendarWidget()
            if calendar is not None:
                calendar.installEventFilter(filt)

    # ---------- dates ----------

    @staticmethod
    def _configure_optional_date(date_edit: QDateEdit):
        date_edit.setSpecialValueText(" ")
        date_edit.setMinimumDate(QDate(1, 1, 1))
        date_edit.setMaximumDate(QDate(9999, 12, 31))
        date_edit.setDate(date_edit.minimumDate())
        calendar = date_edit.calendarWidget()
        if calendar is not None:
            # Wide hard range; per-field floors applied later with signals blocked.
            set_calendar_selectable_range(
                date_edit,
                QDate(_EARLIEST_REAL_YEAR, 1, 1),
                QDate(9999, 12, 31),
            )
        polish_date_edit_calendar(date_edit, blank_opens_at_default_year=True)

    def _clear_date(self, date_edit: QDateEdit):
        date_edit.setMinimumDate(QDate(1, 1, 1))
        date_edit.setDate(date_edit.minimumDate())

    def _date_or_none(self, date_edit: QDateEdit):
        value = date_edit.date()
        if _is_blank_project_date(value):
            return None
        return value

    def _refresh_date_calendar_bounds(self):
        """Simple floors: start/end ≥ receive; end ≥ start. Receive unconstrained."""
        floor = QDate(_EARLIEST_REAL_YEAR, 1, 1)
        ceiling = QDate(9999, 12, 31)
        recv = self._date_or_none(self.date_receive)
        start = self._date_or_none(self.date_start)

        set_calendar_selectable_range(self.date_receive, floor, ceiling)

        start_min = recv if recv is not None else floor
        set_calendar_selectable_range(self.date_start, start_min, ceiling)

        if start is not None:
            end_min = start
        elif recv is not None:
            end_min = recv
        else:
            end_min = floor
        set_calendar_selectable_range(self.date_end, end_min, ceiling)

    def _sync_dates_to_state(self):
        recv = self._date_or_none(self.date_receive)
        start = self._date_or_none(self.date_start)
        end = self._date_or_none(self.date_end)
        self.state.sample_receive_date = recv.toString("yyyy-MM-dd") if recv else ""
        self.state.test_start_date = start.toString("yyyy-MM-dd") if start else ""
        self.state.test_end_date = end.toString("yyyy-MM-dd") if end else ""

    def _apply_date_string(self, date_edit, date_str):
        parsed = QDate.fromString(date_str or "", "yyyy-MM-dd")
        if parsed.isValid() and not _is_blank_project_date(parsed):
            date_edit.setDate(parsed)
        else:
            self._clear_date(date_edit)

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
        """Refresh calendar floors; no cross-field auto-rewrite while editing."""
        if getattr(self, "_updating_dates", False):
            return
        self._updating_dates = True
        try:
            recv = self._date_or_none(self.date_receive)
            start = self._date_or_none(self.date_start)
            end = self._date_or_none(self.date_end)
            source = self.sender()

            self._refresh_date_calendar_bounds()
            self._sync_dates_to_state()
            self._update_duration_display(start, end)
            if source in (self.date_receive, self.date_start, self.date_end):
                self._mark_dirty()  # no-op when no project is loaded
                if self.leg_graph.is_gantt_mode():
                    self.leg_graph.gantt_chart.refresh()
        finally:
            self._updating_dates = False

    def _project_dates_in_order(self) -> bool:
        """receive ≤ start ≤ end (same day allowed). Missing dates are not ordered."""
        recv = self._date_or_none(self.date_receive)
        start = self._date_or_none(self.date_start)
        end = self._date_or_none(self.date_end)
        if recv is None or start is None or end is None:
            return False
        return recv <= start <= end

    def _update_duration_display(self, start, end):
        if start is None or end is None:
            self.txt_duration.setText("")
            return
        # Inclusive test days: 19–20 counts as 2.
        self.txt_duration.setText(str(start.daysTo(end) + 1))

    # ---------- export target UI ----------

    def _on_export_mode_changed(self):
        mode = self.combo_export_mode.currentText()
        self.combo_export_target.blockSignals(True)
        self.combo_export_target.clear()

        if mode == "全部 Leg":
            self.combo_export_target.setEnabled(False)
            self.combo_export_target.addItem("全部 Leg")
        elif mode == "单条 Leg":
            self.combo_export_target.setEnabled(True)
            legs = self.state.legs or []
            if not legs:
                self.combo_export_target.addItem("（当前无 Leg）")
                self.combo_export_target.setEnabled(False)
            else:
                for leg in legs:
                    self.combo_export_target.addItem(leg.leg_name, userData=leg.leg_id)
        else:  # 单项试验
            self.combo_export_target.setEnabled(True)
            found = False
            for leg in self.state.legs or []:
                for node in leg.nodes:
                    if not node.test_name:
                        continue
                    found = True
                    self.combo_export_target.addItem(
                        f"{leg.leg_name} / {node.test_name}",
                        userData=f"TEST:{leg.leg_name} - {node.test_name}",
                    )
            if not found:
                self.combo_export_target.addItem("（当前无试验）")
                self.combo_export_target.setEnabled(False)

        self.combo_export_target.blockSignals(False)

    # ---------- dirty / mirror helpers ----------

    def _mark_dirty(self):
        # Date-only edits with no loaded project are not savable — ignore them.
        if not self.state.project_id:
            return
        self._is_dirty = True

    def _has_unsaved_changes(self):
        return bool(self._is_dirty and self.state.project_id)

    def _on_structure_changed(self):
        self._mark_dirty()
        self._on_export_mode_changed()

    def _set_mirror_status(self, text, kind="dim"):
        names = {"dim": "dimLabel", "ok": "hintLabel", "err": "errorLabel"}
        self.lbl_mirror_status.setText(text or "")
        self.lbl_mirror_status.setObjectName(names.get(kind, "dimLabel"))
        self.lbl_mirror_status.style().unpolish(self.lbl_mirror_status)
        self.lbl_mirror_status.style().polish(self.lbl_mirror_status)
        ready = (
            kind == "ok"
            and self._local_path is not None
            and self._local_path.is_dir()
        )
        self.btn_open_local.setVisible(ready)

    def _open_local_project_folder(self):
        path = self._local_path
        if path is None or not path.is_dir():
            QMessageBox.warning(self, "提示", "本地镜像尚未就绪")
            return
        subprocess.run(["open", str(path)])

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
        if not self._has_unsaved_changes():
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

    def save_state(self, show_success=True):
        if not self.state.project_id:
            QMessageBox.warning(self, "提示", "请先加载项目")
            return False
        self._sync_dates_to_state()
        if self.state.duplicate_test_names():
            warn_duplicate_test_names(self)
            return False
        if self._local_path is None:
            self._local_path = local_project_dir(self.state.project_id)
        self._local_path.mkdir(parents=True, exist_ok=True)
        self.state.project_path = str(self._local_path)
        save_path = self._local_path / "project_state.json"
        self.state.save_to_file(str(save_path))
        self._is_dirty = False
        if show_success:
            SaveSuccessDialog(self).exec()
        return True

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
        self._set_path_text(loaded.source_path or str(saved.local_path))
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
        try:
            catalog = self.leg_graph.db_loader.load_standards() if self.leg_graph.db_loader else []
        except DuplicateStandardError as exc:
            QMessageBox.warning(self, "提示", duplicate_standard_message(exc))
            return
        apply_leg_template(self.state, name, legs, catalog=catalog)
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

        self._sync_dates_to_state()
        if not self.state.sample_receive_date:
            QMessageBox.warning(self, "无法导出", "样品接收日期未记录")
            return
        if not self.state.test_start_date:
            QMessageBox.warning(self, "无法导出", "开始时间未记录")
            return
        if not self.state.test_end_date:
            QMessageBox.warning(self, "无法导出", "结束时间未记录")
            return
        if not self._project_dates_in_order():
            QMessageBox.warning(
                self,
                "无法导出",
                "日期顺序无效：样品接收日期 ≤ 试验开始 ≤ 试验结束（允许同一天）",
            )
            return

        try:
            from src.generators.word_engine import WordGenerator

            lang, ok = QInputDialog.getItem(
                self,
                "选择报告语言",
                "请选择要生成的报告语言：",
                ["中文", "英文", "中英文"],
                0,
                False,
            )
            if not ok:
                return

            default_no = WordGenerator.default_report_no(self.state, lang)
            report_no, ok = QInputDialog.getText(
                self,
                "请确认报告编号",
                "请确认报告编号：",
                text=default_no,
            )
            if not ok:
                return
            report_no = (report_no or "").strip()
            if not report_no:
                QMessageBox.warning(self, "无法导出", "报告编号不能为空")
                return

            template_by_lang = {
                "中文": Path("templates/template_zh.docx"),
                "英文": Path("templates/template_en.docx"),
                "中英文": Path("templates/template_ze.docx"),
            }
            template_path = template_by_lang.get(lang, Path("templates/template_zh.docx"))
            if not template_path.exists() and lang == "中文":
                template_path = Path("templates/template_raw.docx")
            if not template_path.exists():
                QMessageBox.warning(self, "错误", f"找不到模板文件: {template_path}")
                return

            stem = WordGenerator.report_filename_stem(report_no)
            out_name = f"{stem}.docx"
            project_path = self._local_path

            if project_path and project_path.is_dir():
                report_dir = project_path / "4.报告组"
                report_dir.mkdir(exist_ok=True)
                out_path = report_dir / out_name
            else:
                report_dir = Path(".scratch")
                report_dir.mkdir(parents=True, exist_ok=True)
                out_path = report_dir / out_name

            if out_path.exists():
                reply = QMessageBox.question(
                    self,
                    "存在同名报告",
                    f"已存在同名报告「{out_name}」，是否覆盖？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    out_path.unlink()
                else:
                    out_path = WordGenerator.next_duplicate_report_path(report_dir, stem)

            engine = WordGenerator(str(template_path))
            mode = self.combo_export_mode.currentText()
            target_project_path = str(project_path) if project_path else None
            target_text = self.combo_export_target.currentText()

            if mode == "单条 Leg":
                leg_filter = self.combo_export_target.currentData()
                if not leg_filter:
                    QMessageBox.warning(self, "错误", "请先选择要导出的 Leg")
                    return
                scope_note = f"\n导出范围: Leg → {target_text}"
            elif mode == "单项试验":
                leg_filter = self.combo_export_target.currentData()
                if not leg_filter:
                    QMessageBox.warning(self, "错误", "请先选择要导出的试验")
                    return
                scope_note = f"\n导出范围: 试验 → {target_text}"
            else:
                leg_filter = None
                scope_note = "\n导出范围: 全部 Leg"

            incomplete = self.state.incomplete_export_labels(leg_filter)
            if incomplete:
                QMessageBox.warning(
                    self,
                    "无法导出",
                    "以下试验尚未完成明细（含关键参数确认），无法导出报告：\n"
                    + "\n".join(incomplete),
                )
                return

            engine.generate(
                self.state, str(out_path),
                project_path=target_project_path, leg_filter=leg_filter,
                report_language=lang,
                report_no=report_no,
            )

            msg = QMessageBox(self)
            msg.setWindowTitle("导出成功")
            msg.setText(
                f"报告已生成至:\n{out_path}"
                f"{scope_note}\n报告语言: {lang}\n报告编号: {report_no}"
            )
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
