import sys
from pathlib import Path

# Ensure src is in path if run directly
sys.path.append(str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from src.ui.main_window import MainWindow
from src.ui.theme import apply_cyberpunk_theme

def main():
    app = QApplication(sys.argv)
    apply_cyberpunk_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
