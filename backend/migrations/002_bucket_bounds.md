# 002 区间车数与周账上下限

新增区间口径下的独立数据与运行表，不改动既有 `datasets`、`runs` 等表；应用启动仍由
`Base.metadata.create_all` 补建缺失表，已存在的表不受影响。

- `bucket_gate_datasets`：门岗区间车数批次，按名称与 SHA-256 去重，行内保存各等待区间车辆数。
- `bucket_ledger_datasets`：周总等待分钟批次，按业务名称版本化（`name + version` 唯一），
  同名再次导入产生新版本，用于驱动上游更新后的失效重算。
- `bound_runs`：双重差分上下限运行，记录门岗/周账批次、参数、结果、导出文件与租约；
  `stale`、`stale_reason` 标记上游失效，`superseded_by` / `replaces_run_id` 记录替换血缘，
  `ledger_version` 冗余保存所用周账版本。新增状态值 `superseded`（已替换失效）。

升级方式：重启后端即自动补建三张表；既有运行与均值批次流程不变。
