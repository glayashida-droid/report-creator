import sys
import os
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                               QListWidget, QGroupBox, QSplitter, QComboBox, QMessageBox)
from PySide6.QtCore import Qt
import subprocess

# Ensure src is in path if run directly
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.models.project_state import ProjectState
from application_parser import parse_application, prepare_excel_bytes
from src.parsers.pdf_parser import QuotationParser

from src.ui.leg_graph import LegGraphArea

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Report Creator")
        self.resize(1000, 700)
        self.state = ProjectState()
        
        self.init_ui()
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # 1. Top Panel: Project Locator
        top_panel = QGroupBox("项目定位")
        top_layout = QHBoxLayout(top_panel)
        
        self.txt_project_id = QLineEdit()
        self.txt_project_id.setPlaceholderText("输入项目号并回车 (例如: A2260613686101)")
        btn_load_project = QPushButton("加载项目文件夹")
        btn_load_project.clicked.connect(self.load_project)
        
        top_layout.addWidget(QLabel("项目号:"))
        top_layout.addWidget(self.txt_project_id)
        top_layout.addWidget(btn_load_project)
        
        main_layout.addWidget(top_panel)
        
        # Splitter for Main Content
        splitter = QSplitter(Qt.Horizontal)
        
        # 2. Left Panel: Project Info & Candidate Pool
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # 2.1 Applicant Info
        info_group = QGroupBox("申请单信息")
        info_layout = QVBoxLayout(info_group)
        self.lbl_applicant = QLabel("申请公司: 未加载")
        self.lbl_sample = QLabel("样品名称: 未加载")
        info_layout.addWidget(self.lbl_applicant)
        info_layout.addWidget(self.lbl_sample)
        left_layout.addWidget(info_group)
        
        # 2.2 Candidate Pool
        pool_group = QGroupBox("项目候选池 (从报价单提取)")
        pool_layout = QVBoxLayout(pool_group)
        self.list_candidates = QListWidget()
        pool_layout.addWidget(self.list_candidates)
        left_layout.addWidget(pool_group)
        
        # 2.3 Export panel
        export_panel = QGroupBox("导出报告")
        export_layout = QHBoxLayout(export_panel)
        
        self.combo_export_mode = QComboBox()
        self.combo_export_mode.addItems(["导出全部 Leg"])
        self.btn_export = QPushButton("一键生成报告")
        self.btn_export.clicked.connect(self.export_report)
        
        export_layout.addWidget(QLabel("导出模式:"))
        export_layout.addWidget(self.combo_export_mode)
        export_layout.addWidget(self.btn_export)
        export_layout.addStretch()
        
        left_layout.addWidget(export_panel)
        
        splitter.addWidget(left_panel)
        
        # 3. Right Panel: Leg Graph Area (Placeholder for TKT-5)
        self.right_panel = QGroupBox("Leg 图排布区")
        right_layout = QVBoxLayout(self.right_panel)
        
        self.leg_graph = LegGraphArea(self.state)
        self.leg_graph.btn_save.clicked.connect(self.save_state)
        right_layout.addWidget(self.leg_graph)
        
        splitter.addWidget(self.right_panel)
        
        # Set splitter proportions (Left 1 : Right 3)
        splitter.setSizes([250, 750])
        main_layout.addWidget(splitter)
        
    def load_project(self):
        project_id = self.txt_project_id.text().strip()
        if not project_id:
            return
            
        base_dir = Path("example")
        # In a real scenario, this would search the shared drive.
        # For now, we just check if it exists in example/
        project_path = None
        for p in base_dir.iterdir():
            if p.is_dir() and project_id in p.name:
                project_path = p
                break
                
        if not project_path:
            self.lbl_applicant.setText("未找到对应文件夹")
            return
            
        self.state.project_id = project_id
        
        # Step 1: Find Application Excel in 1.接样组
        sample_dir = project_path / "1.接样组"
        app_excel = None
        quote_pdf = None
        
        if sample_dir.exists():
            for f in sample_dir.iterdir():
                if f.name.endswith('.xlsx'):
                    app_excel = f
                elif f.name.endswith('.pdf') and '报价单' in f.name:
                    quote_pdf = f
                    
        # Parse Excel
        if app_excel:
            try:
                raw = app_excel.read_bytes()
                clean, name = prepare_excel_bytes(raw, app_excel.name)
                data = parse_application(clean, name)
                
                self.state.applicant_name = data.applicant_name_cn
                self.state.sample_name = data.sample_info.get("样品名称", "")
                
                self.lbl_applicant.setText(f"申请公司: {self.state.applicant_name}")
                self.lbl_sample.setText(f"样品名称: {self.state.sample_name}")
            except Exception as e:
                self.lbl_applicant.setText(f"解析申请单失败: {e}")
                
        # Parse PDF
        self.list_candidates.clear()
        if quote_pdf:
            try:
                items = QuotationParser.extract_test_items(str(quote_pdf))
                items = [it for it in items if it != "服务项目Service Item"]
                self.state.candidate_pool = items
                self.list_candidates.addItems(items)
                
                # Notify leg graph
                self.leg_graph.notify_pool_changed()
            except Exception as e:
                self.list_candidates.addItem(f"解析报价单失败: {e}")
                
    def save_state(self):
        if not self.state.project_id:
            print("No project loaded")
            return
            
        save_path = f".scratch/{self.state.project_id}_state.json"
        self.state.save_to_file(save_path)
        print(f"State saved to {save_path}")

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
            # Try to save in the project's report folder
            base_dir = Path("example")
            project_path = None
            for p in base_dir.iterdir():
                if p.is_dir() and self.state.project_id in p.name:
                    project_path = p
                    break
                    
            if project_path:
                report_dir = project_path / "4.报告组"
                report_dir.mkdir(exist_ok=True)
                out_path = report_dir / out_name
            else:
                out_path = Path(".scratch") / out_name
                
            engine = WordGenerator(str(template_path))
            # Just do ALL legs for this MVP
            engine.generate(self.state, str(out_path), project_path=str(project_path) if project_path else None)
            
            msg = QMessageBox(self)
            msg.setWindowTitle("导出成功")
            msg.setText(f"报告已生成至:\n{out_path}")
            
            btn_open = msg.addButton("打开所在文件夹", QMessageBox.ActionRole)
            msg.addButton(QMessageBox.Ok)
            msg.exec()
            
            if msg.clickedButton() == btn_open:
                # macOS specific
                subprocess.run(["open", "-R", str(out_path)])
                
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"生成报告时发生错误:\n{str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
