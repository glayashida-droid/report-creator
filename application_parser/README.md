# application_parser — 申请单客户/样品信息抽取包

从 **ai_report** 稽核系统抽出的独立包：只解析申请单 **第 1 页（客户/应选信息）** 与 **第 2 页（样品信息）**，以及 **沃尔沃/极星单页申请单** 的同等字段。

**故意不包含**：第 3 页「测试信息 / 试验项目」、大纲、报告比对规则。

---

## 怎么接到新程序

1. 把整个目录 `application_parser/` 复制到新项目根目录（或任意 `PYTHONPATH` 下的包路径）。
2. 安装依赖：

```bash
pip install -r application_parser/requirements.txt
# 即：openpyxl、pydantic
```

3. 调用：

```python
from pathlib import Path
from application_parser import parse_application, prepare_excel_bytes, ApplicationData

raw = Path("A22606612351.xlsx").read_bytes()
# WPS 导出的 xlsx 建议先预处理（剥离 openpyxl 不认的数据验证）
clean, name = prepare_excel_bytes(raw, "A22606612351.xlsx")

data: ApplicationData = parse_application(clean, name)
# 沃尔沃/极星 QP-VBD 单页格式：
# data = parse_application(clean, name, volvo=True)

print(data.applicant_name_cn, data.applicant_address_cn)
print(data.sample_info)                 # 含「申请单号」等键值
print(data.sample_info_candidates)      # 多样品列候选
print(data.report_title_name_cn)        # 报告抬头（若与申请公司不同）
```

---

## 调用链（读代码按这个顺序）

```
parse_application(file_bytes, filename, volvo=False)
│
├─ volvo=True ─────────────────────────────────────────────┐
│                                                          │
│   excel_volvo.parse_volvo_application                    │
│     ├─ encoding_io.load_workbook_from_bytes              │
│     ├─ 定位沃尔沃工作表 / 合并单元格                       │
│     ├─ 委托方块 _parse_applicant_block                   │
│     ├─ 报告抬头勾选 excel_checkbox + 补充公司/地址        │
│     ├─ 样品区 _parse_sample_block / _parse_pre_sample…   │
│     └─ 申请单号注入 sample_info["申请单号"]               │
│                                                          │
└─ volvo=False（标准 CTI 三页模板，只读前两页）─────────────┘
      excel_parser.parse_application
        ├─ encoding_io.load_workbook_from_bytes
        ├─ excel_sheet_locate.find_application_selection_sheet  # 「应选信息」
        │     └─ parse_application_sheet1
        │           委托方中/英名称地址、申请单号、报告抬头
        │           （field_extract_applicant：同申请公司/同付款方占位解析）
        ├─ excel_sheet_locate.find_application_sample_sheet     # 「样品信息」
        │     └─ parse_application_sheet2
        │           sample_info / sample_info_candidates / sample_column_names
        ├─ parse_application_selection_sample_fields（应选页同行样品字段）
        │     └─ 与 Sheet2 冲突时按包含关系择优
        └─ 将申请单号插入 sample_info 首位
              → 返回 ApplicationData
```

可选前置：

```
prepare_excel_bytes / prepare_excel_upload   # excel_prepare.py
  → 清洗 WPS type=any 等数据验证后再交给 parse_application
```

---

## 返回字段（`ApplicationData`）

| 字段 | 含义 |
|------|------|
| `source.filename` | 源文件名 |
| `applicant_name` / `_cn` / `_en` | 委托方名称（综合 / 中 / 英） |
| `applicant_address` / `_cn` / `_en` | 委托方地址 |
| `report_title_name_*` / `report_title_address_*` | 报告抬头公司/地址 |
| `sample_info` | 样品字段字典；**含** `申请单号`（若有） |
| `sample_info_candidates` | 同行多样品列的候选值列表 |
| `sample_column_names` | Sheet2 各列样品名称（001/002…） |

定义见 `models.py`。

---

## 文件说明

| 文件 | 职责 |
|------|------|
| `__init__.py` | 公开 API |
| `models.py` | `ApplicationData` / `FileSource` |
| `excel_parser.py` | **标准申请单主入口** `parse_application` + Sheet1/2 解析 |
| `excel_volvo.py` | 沃尔沃/极星单页 `parse_volvo_application` |
| `excel_sheet_locate.py` | 按标签页名定位「应选信息」「样品信息」 |
| `excel_checkbox.py` | 沃尔沃是/否勾选框（VML） |
| `excel_prepare.py` | 上传前清洗 xlsx |
| `encoding_io.py` | `safe_text` / `load_workbook_from_bytes` |
| `field_extract_applicant.py` | 委托方双语、「同申请公司」等 |
| `field_extract_labels.py` | 标签清洗、样品键归一 |
| `field_extract_*.py` | 空值/数量/别名/多样品匹配辅助 |
| `field_extract.py` | 上述符号的统一 re-export |
| `report_language.py` | 英文字段标签 → 中文键 |
| `sample_id_labels.py` / `_stubs.py` | 精简占位，避免 Word/LLM 依赖 |

---

## 与 ai_report 主仓的关系

- 源逻辑来自 `src/parser/excel_parser.py`、`excel_volvo.py` 等。
- 本包已去掉第 3 页大纲解析与 `OutlineData`。
- 主仓继续演进时，若要同步行为，以主仓对应文件为准再重新导出。

---

## 自检

在**包含本包父目录**的 Python 路径下：

```bash
python -c "
from application_parser import parse_application
print(parse_application)
"
```
