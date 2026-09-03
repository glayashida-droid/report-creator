# TKT-1: 公盘 JSON 读写（打开拉公盘 · 保存先公盘）

labels: `ready-for-agent`

## Parent

[docs/specs/nightly-backup-and-cloud-photos.md](../../../../docs/specs/nightly-backup-and-cloud-photos.md)

## Demo path

从「加载明细」选已有项目 → 程序按 `source_path` 读公盘 `project_state.json` 进 UI，并写本地缓存；改 Leg/排期后点保存明细 → 公盘 JSON 先更新，再写 `data/{项目号}/project_state.json`；公盘不可写时保存失败并保留 dirty，不静默丢数据。

## Objective

打通 JSON 权威在公盘的第一条垂直路径：打开、保存、本地缓存供看板扫描。他人加载同一公盘项目时能看到最新排期（US-01、02、04、05、06 之 JSON 部分、30、31）。

## Requirements

* 新增 JSON lifecycle API（可放在 `project_sync` 或 `project_mirror`）：`load_json_from_remote(remote_root)`、`save_json_to_remote_then_local(state, local_root, remote_root)`。
* `load_saved_state` / `load_project_folder`：有可用 `source_path` 时读公盘 JSON；公盘 mtime 新于本地缓存时提示是否用公盘覆盖（默认倾向公盘）。
* `save_state`：公盘写入成功后才写本地缓存并清 dirty；失败则提示、保持 dirty。
* `source_path` 不可访问：允许仅用本地缓存打开，并提示公盘不可用（可标记待同步，照片同步留给 TKT-6）。
* 看板 `list_saved_projects` 仍扫本地 `data/*/project_state.json`，无需改扫描方式。
* 模块单测：`tmp_path` 下 remote/local 双根，覆盖保存顺序、公盘新于本地、公盘写失败。

## Blocked by

* None (can start immediately)

## Acceptance criteria

- [x] 保存明细后，公盘项目根存在最新 `project_state.json`，且本地缓存与其一致。
- [x] 从加载明细打开项目时，若公盘 JSON 较新，用户被提示并可用公盘版本加载。
- [x] 公盘不可写时，保存失败或明确待同步，本地 dirty 不丢。
- [x] JSON lifecycle 模块测试在基线上红、合并后绿。
