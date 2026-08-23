# vulnhunt 配置项

## 1. 加载优先级

```
config.toml  →  VULNHUNT_<字段大写> 环境变量  →  代码内覆盖值(overrides)
```

实现见 `src/vulnhunt/config.py` 的 `load_config(path, overrides)`：先读 toml，再逐字段查 `os.environ`，最后应用调用方覆盖。bool 型环境变量按 `"true"/"1"/"yes"/"on"` 解析；解析失败静默忽略该项。

## 2. 当前项目 config.toml

```toml
runs_root = "../vulnhunt-runs"  # 运行记录根目录（本地指向仓库外的 vulnhunt-runs）
max_rounds = 50               # 最大轮次
max_workers = 10              # 并行 Codex 数
codex_timeout_s = 100000000   # 单任务 codex 超时（秒）；一亿≈暂不禁用，后续再收紧
```

## 3. 字段对照表

`Config` 代码默认值 vs 项目 config.toml 实际值。当前保留的字段均为**实际生效**（在源码某处被读取）；历史遗留的未生效字段（`plan_retry_max`、`claude_permission_mode`、`claude_model`、`codex_model`、`codex_approve_for_me`、`coverage_threshold`、`max_rounds_no_progress`、`verbose`、`target_dir`、`target_extra_dirs`）已删除。

| 字段 | 代码默认 | 项目 config.toml | 实际是否生效 |
|---|---|---|---|
| `runs_root` | `"runs"` | `"vulnhunt-runs"` | ✅ `state.py RunStore.create` |
| `max_rounds` | `5` | `50` | ✅ `orchestrator.py` DECISION 判断 |
| `max_workers` | `3` | `10` | ✅ `workers.py ThreadPoolExecutor` |
| `claude_timeout_s` | `900` | — | ✅ `claude_code.py run_process` |
| `codex_timeout_s` | `100_000_000` | `100000000` | ✅ `codex.py run_process` |
| `codex_sandbox` | `"danger-full-access"` | — | ✅ `codex.py` 的 `-s` 参数 |
| `claude_exec` | `"claude"` | — | ✅ `claude_code.py` |
| `codex_exec` | `"codex"` | — | ✅ `codex.py` |

> 若未来需要 claude/codex 的 model、permission 模式、停滞检测等参数，需**重新添加字段并接线**（入口见 [development.md](development.md)）。
> 黑板目录固定在 `<run_dir>/blackboard/`，由 run 目录派生，非配置项。

## 4. 环境变量用法示例

```bash
# 不编辑 config.toml，临时改并发与超时
VULNHUNT_MAX_WORKERS=5 VULNHUNT_CODEX_TIMEOUT_S=1200 vulnhunt start "审计 xxx"
```

字段名转大写前缀 `VULNHUNT_`：`max_workers` → `VULNHUNT_MAX_WORKERS`。
