# vulnhunt 配置项

## 1. 加载优先级

```
config.toml  →  VULNHUNT_<字段大写> 环境变量  →  代码内覆盖值(overrides)
```

实现见 `src/vulnhunt/config.py` 的 `load_config(path, overrides)`：先读 toml，再逐字段查 `os.environ`，最后应用调用方覆盖。bool 型环境变量按 `"true"/"1"/"yes"/"on"` 解析；解析失败静默忽略该项。

## 2. 当前项目 config.toml（唯一来源，代码不兜底）

```toml
# vulnhunt 统一配置（唯一来源，代码不兜底）。
# 加载优先级：本文件 → VULNHUNT_<字段大写> 环境变量 → 调用方覆盖。
# 全部字段必须存在（缺一即 load_config 报错）；字段与 src/vulnhunt/config.py 的 Config 一一对应。

claude_exec = "claude"               # claude CLI 可执行文件名或绝对路径（规划大脑；vulnhunt doctor 可自检）
codex_exec = "codex"                 # codex CLI 可执行文件名或绝对路径（执行手）
runs_root = "../vulnhunt-runs"       # 运行记录根目录（本地指向仓库外的 vulnhunt-runs）
max_rounds = 15                      # 最大轮次上限：规划器渐进推进，代码在 DECISION 阶段硬卡此上限
max_workers = 10                     # 并行 Codex 数：ThreadPoolExecutor 并发上限，超出部分任务被丢弃不排队
claude_timeout_s = 900               # 单轮 claude 规划超时（秒），超时强杀
codex_timeout_s = 100000000          # 单任务 codex 超时（秒）；一亿≈暂不禁用，后续再收紧
codex_sandbox = "danger-full-access" # codex 沙箱权限声明（-s 参数）；仅对授权目标使用
prettier_max_bytes = 1000000         # 黑板 JS 静默格式化大小阈值（字节），超过视为压缩产物跳过
```

## 3. 字段对照表

`Config` 数据类**无任何默认值**（配置不兜底），全部字段必须由 config.toml / `VULNHUNT_*` 环境变量 / 调用方覆盖提供，缺一即 `load_config` 抛错。当前保留的字段均为**实际生效**（在源码某处被读取）；历史遗留的未生效字段（`plan_retry_max`、`claude_permission_mode`、`claude_model`、`codex_model`、`codex_approve_for_me`、`coverage_threshold`、`max_rounds_no_progress`、`verbose`、`target_dir`、`target_extra_dirs`）已删除。

| 字段 | 项目 config.toml | 实际是否生效 |
|---|---|---|
| `claude_exec` | `"claude"` | ✅ `claude_code.py` |
| `codex_exec` | `"codex"` | ✅ `codex.py` |
| `runs_root` | `"../vulnhunt-runs"` | ✅ `state.py RunStore.create` |
| `max_rounds` | `15` | ✅ `orchestrator.py` DECISION 判断 |
| `max_workers` | `10` | ✅ `workers.py ThreadPoolExecutor` |
| `claude_timeout_s` | `900` | ✅ `claude_code.py run_process` |
| `codex_timeout_s` | `100000000` | ✅ `codex.py run_process` |
| `codex_sandbox` | `"danger-full-access"` | ✅ `codex.py` 的 `-s` 参数 |
| `prettier_max_bytes` | `1000000` | ✅ `blackboard.py format_blackboard_js` 阈值 |

> 若未来需要 claude/codex 的 model、permission 模式、停滞检测等参数，需**重新添加字段并接线**（入口见 [development.md](development.md)）。
> 黑板目录固定在 `<run_dir>/blackboard/`，由 run 目录派生，非配置项。

## 4. 环境变量用法示例

```bash
# 不编辑 config.toml，临时改并发与超时
VULNHUNT_MAX_WORKERS=5 VULNHUNT_CODEX_TIMEOUT_S=1200 vulnhunt start "审计 xxx"
```

字段名转大写前缀 `VULNHUNT_`：`max_workers` → `VULNHUNT_MAX_WORKERS`。
