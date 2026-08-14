"""Cyberpunk / Premium Dark theme for Report Creator."""

# Palette
BG = "#0D1117"
BG_PANEL = "#12181F"
BG_INPUT = "#0A0E14"
BG_HOVER = "#1A2330"
TEXT = "#E6EDF3"
TEXT_DIM = "#8B949E"
CYAN = "#00FFFF"
MAGENTA = "#FF00FF"
BORDER = "#1F2A37"
CYAN_DIM = "rgba(0, 255, 255, 0.35)"
MAGENTA_DIM = "rgba(255, 0, 255, 0.35)"

CYBERPUNK_QSS = f"""
/* ---- Global ---- */
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "PingFang SC", "Helvetica Neue", "Segoe UI", sans-serif;
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {BG};
}}

QToolTip {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {CYAN};
    padding: 4px 8px;
}}

/* ---- Group boxes (section frames) ---- */
QGroupBox {{
    background-color: {BG_PANEL};
    border: 1px solid {CYAN_DIM};
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 8px;
    color: {CYAN};
    background-color: {BG_PANEL};
}}

QGroupBox#candidatePool {{
    padding: 4px 4px 4px 4px;
    margin-top: 12px;
}}

QGroupBox#candidatePool QListWidget {{
    padding: 2px;
}}

QGroupBox#candidatePool QListWidget::item {{
    padding: 1px 6px;
    margin: 0px;
    border-radius: 4px;
}}

QGroupBox#exportPanel {{
    padding: 4px 6px 6px 6px;
    margin-top: 12px;
}}

QGroupBox#detailGroup {{
    padding: 0px;
    margin-top: 14px;
}}

QGroupBox#overviewGroup {{
    padding: 0px;
    margin-top: 14px;
}}

QFrame#drawerSection {{
    background-color: {BG_PANEL};
    border: 1px solid {CYAN_DIM};
    border-radius: 10px;
}}

QFrame#drawerHeader {{
    background-color: transparent;
    border: none;
    border-radius: 10px;
}}

QFrame#drawerHeader:hover {{
    background-color: {BG_HOVER};
}}

QLabel#drawerTitle, QLabel#drawerArrow {{
    color: {CYAN};
    font-weight: 600;
    background: transparent;
}}

QWidget#drawerBody {{
    background: transparent;
    border: none;
}}

QFormLayout {{
    background: transparent;
}}

QLabel {{
    background: transparent;
    color: {TEXT};
}}

QLabel#dimLabel {{
    color: {TEXT_DIM};
}}

QLabel#hintLabel {{
    color: {CYAN};
}}

QLabel#errorLabel {{
    color: {MAGENTA};
}}

/* ---- Line edits / date edits ---- */
QLineEdit, QDateEdit, QAbstractSpinBox {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {MAGENTA};
    selection-color: {BG};
}}

QLineEdit:hover, QDateEdit:hover, QAbstractSpinBox:hover {{
    border: 1px solid {CYAN_DIM};
}}

QLineEdit:focus, QDateEdit:focus, QAbstractSpinBox:focus {{
    border: 1px solid {CYAN};
    /* simulated neon glow */
    background-color: #0C121A;
}}

QLineEdit:disabled, QDateEdit:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}

QTextEdit {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: {MAGENTA};
    selection-color: {BG};
}}

QTextEdit:focus {{
    border: 1px solid {CYAN};
}}

QDateEdit::drop-down, QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    border: none;
    width: 22px;
    background: transparent;
}}

QDateEdit::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {CYAN};
    width: 0;
    height: 0;
    margin-right: 6px;
}}

/* Calendar popup */
QCalendarWidget {{
    background-color: {BG_PANEL};
    border: 1px solid {CYAN};
    border-radius: 8px;
}}

QCalendarWidget QWidget {{
    background-color: {BG_PANEL};
    color: {TEXT};
}}

QCalendarWidget QToolButton {{
    background-color: transparent;
    color: {CYAN};
    border: none;
    border-radius: 4px;
    padding: 4px;
}}

QCalendarWidget QToolButton:hover {{
    background-color: {BG_HOVER};
    color: {MAGENTA};
}}

QCalendarWidget QAbstractItemView:enabled {{
    selection-background-color: {MAGENTA};
    selection-color: {BG};
}}

/* ---- Combo boxes ---- */
QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 20px;
}}

QComboBox:hover {{
    border: 1px solid {CYAN_DIM};
}}

QComboBox:focus, QComboBox:on {{
    border: 1px solid {CYAN};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {CYAN};
    width: 0;
    height: 0;
    margin-right: 8px;
}}

QComboBox QLineEdit {{
    background-color: transparent;
    border: none;
    padding: 0px;
    min-height: 18px;
}}

QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {CYAN};
    selection-background-color: {MAGENTA};
    selection-color: {BG};
    outline: 0;
    padding: 4px;
}}

/* ---- Buttons ---- */
QPushButton {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {CYAN};
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 600;
    min-height: 22px;
}}

QPushButton:hover {{
    background-color: {BG_HOVER};
    border: 1px solid {CYAN};
    color: {CYAN};
}}

QPushButton:pressed {{
    background-color: #0A1520;
    border: 1px solid {MAGENTA};
    color: {MAGENTA};
}}

QPushButton:disabled {{
    border-color: {BORDER};
    color: {TEXT_DIM};
}}

QPushButton#primaryButton {{
    border: 1px solid {MAGENTA};
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(0, 255, 255, 0.12),
        stop:1 rgba(255, 0, 255, 0.18)
    );
    color: {TEXT};
}}

QPushButton#primaryButton:hover {{
    border: 1px solid {CYAN};
    color: {CYAN};
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(0, 255, 255, 0.22),
        stop:1 rgba(255, 0, 255, 0.28)
    );
}}

QPushButton#accentButton {{
    border: 1px solid {MAGENTA};
}}

QPushButton#accentButton:hover {{
    color: {MAGENTA};
    border: 1px solid {MAGENTA};
}}

QPushButton#nodeDetailButton {{
    padding: 0px 10px;
    min-height: 22px;
    max-height: 28px;
    border-radius: 6px;
    font-size: 12px;
}}

QPushButton#nodeDeleteButton {{
    color: {CYAN};
    background-color: {BG_INPUT};
    border: 1px solid {MAGENTA};
    border-radius: 6px;
    padding: 0px;
    font-size: 15px;
    font-weight: 700;
    min-height: 22px;
    max-height: 28px;
}}

QLabel#nodeCompleteMark {{
    background: transparent;
    color: {CYAN};
    font-size: 16px;
    font-weight: 700;
    padding: 0px;
}}

QPushButton#nodeDeleteButton:hover {{
    color: {BG};
    background-color: {MAGENTA};
    border: 1px solid {CYAN};
}}

QPushButton#fieldRemoveButton {{
    color: {CYAN};
    background-color: {BG_INPUT};
    border: 1px solid {MAGENTA};
    border-radius: 4px;
    padding: 0px;
    font-size: 11px;
    font-weight: 700;
    min-height: 16px;
}}

QPushButton#fieldRemoveButton:hover {{
    color: {BG};
    background-color: {MAGENTA};
    border: 1px solid {CYAN};
}}

QPushButton#poolToggle {{
    padding: 4px 8px;
    min-height: 20px;
    border-radius: 6px;
    font-size: 12px;
}}

QPushButton#poolToggle:checked {{
    background-color: rgba(0, 255, 255, 0.16);
    border: 1px solid {CYAN};
    color: {CYAN};
}}

/* ---- Lists / scroll areas ---- */
QListWidget, QTableWidget, QTreeWidget {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    outline: 0;
    padding: 4px;
}}

QListWidget::item {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    margin: 2px;
}}

QListWidget::item:hover {{
    border: 1px solid {CYAN_DIM};
    color: {CYAN};
}}

QListWidget::item:selected {{
    border: 1px solid {MAGENTA};
    background-color: rgba(255, 0, 255, 0.15);
    color: {TEXT};
}}

QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: {BG};
    width: 10px;
    margin: 0;
    border: none;
}}

QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: {CYAN_DIM};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: none;
}}

QScrollBar:horizontal {{
    background: {BG};
    height: 10px;
    margin: 0;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 5px;
    min-width: 24px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {CYAN_DIM};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    width: 0;
    background: none;
}}

/* ---- Splitter ---- */
QSplitter::handle {{
    background-color: {BORDER};
    width: 2px;
    height: 2px;
}}

QSplitter::handle:hover {{
    background-color: {CYAN};
}}

/* ---- Frames used by Leg cards ---- */
QFrame#legCard, QFrame#testNodeCard {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

QFrame#testNodeCard:hover {{
    border: 1px solid {CYAN_DIM};
}}

/* ---- Message boxes / dialogs ---- */
QMessageBox {{
    background-color: {BG_PANEL};
}}

QMessageBox QLabel {{
    color: {TEXT};
}}

QDialog {{
    background-color: {BG};
}}

QHeaderView::section {{
    background-color: {BG_PANEL};
    color: {CYAN};
    border: 1px solid {BORDER};
    padding: 6px 8px;
}}

QComboBox#bulkResultCombo {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {CYAN_DIM};
    border-radius: 6px;
    padding: 0px 6px;
    min-height: 18px;
    font-size: 12px;
}}

QTableWidget {{
    gridline-color: {BORDER};
    alternate-background-color: {BG_PANEL};
}}

QTableWidget::item:selected {{
    background-color: rgba(255, 0, 255, 0.25);
}}

QInputDialog, QFileDialog {{
    background-color: {BG};
    color: {TEXT};
}}
"""


def apply_cyberpunk_theme(app):
    """Apply the cyberpunk QSS to a QApplication."""
    app.setStyle("Fusion")
    app.setStyleSheet(CYBERPUNK_QSS)
