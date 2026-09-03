# 夜间备份 · 手工验收清单

对照规格 [nightly-backup-and-cloud-photos.md](nightly-backup-and-cloud-photos.md) Further notes。自动化见 `tests/test_nightly_backup_smoke.py`。

## 两日照片循环

1. 打开项目，往正式相册放入图 1–5；「立即备份到公盘」→ 本地原图清除、目录仍在；缩略图为云标记。
2. 下载图 4 到本地；再拷入 6–10。列表：1–3、5 云；4、6–10 无云。
3. 再次备份 → 4、6–10 清本地；导出 Word 含 1–10（正式相册），不含 `备用/`。
4. 删除一张图 → 进 `备用/`，列表与导出不再出现；访达拖回可还原。

## 共享（US-30–32）

1. 机器 A 改排期并保存明细 → 公盘 `project_state.json` 立即更新；顶部「公盘JSON」勾选。
2. 机器 B 从公盘加载同项目 → 见最新排期；A 白天新拖未备份的照片 B 暂时看不到（可接受）。
3. A 夜间/立即备份后，B 刷新见对应云图。

## 连接状态

- 「公盘JSON」：`source_path` 可达即勾；有 `project_state.json` 时 tooltip 显示路径。
- 同步行：「上次同步 HH:MM · 上传 n · 清理 m」（或失败摘要）。
