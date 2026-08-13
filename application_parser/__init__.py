"""申请单客户信息 / 样品信息解析包（自 ai_report 导出）。

公开入口：
    from application_parser import parse_application, prepare_excel_bytes

    data = parse_application(xlsx_bytes, "A2260….xlsx")
    # 沃尔沃/极星单页：
    data = parse_application(xlsx_bytes, "volvo.xlsx", volvo=True)
"""

from application_parser.excel_parser import parse_application
from application_parser.excel_prepare import prepare_excel_upload
from application_parser.models import ApplicationData, FileSource

__all__ = [
    "ApplicationData",
    "FileSource",
    "parse_application",
    "prepare_excel_bytes",
    "prepare_excel_upload",
]


def prepare_excel_bytes(file_bytes: bytes, filename: str) -> tuple[bytes, str]:
    """上传前预处理（剥离 WPS 不兼容数据验证），返回 (bytes, filename)。"""
    return prepare_excel_upload(file_bytes, filename)
