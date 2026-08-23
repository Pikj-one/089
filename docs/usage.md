# vulnhunt 安装与使用

## 1. 安装

```bash
pip install -e .        # 安装后获得 vulnhunt 命令（零第三方依赖，仅需 Python >= 3.11）
```

前置依赖：本地 **`claude`** 与 **`codex`** 两个 CLI 必须在 PATH 中（`vulnhunt doctor` 可检查）。

## 2. 命令一览

| 命令 | 作用 |
|---|---|
| `vulnhunt doctor` | 检查 claude / codex 是否可用 |
| `vulnhunt start "<目标>"` | 非交互式跑一轮完整任务，结束后打印状态 + 报告路径 |
| `vulnhunt tui` | 交互式控制台，实时流式输出；命令：`status` `tasks` `findings` `logs` `claude [round]` `abort` `quit` |
| `vulnhunt resume <run_dir>` | 从 run 目录断点续跑（从 `run.json` 的 current_round 继续） |
| `vulnhunt log <run_dir> [--round N]` | 回放某一轮 claude 的 stream-json 日志 |
| `vulnhunt start <goal> --config <path>` | 指定配置文件（默认 `config.toml`） |

```bash
# 示例
vulnhunt doctor
vulnhunt start "审计 imou.com 登录接口是否存在账号枚举"
vulnhunt tui
vulnhunt resume vulnhunt-runs/2026/08/22/14-30/abc123def456
vulnhunt log vulnhunt-runs/2026/08/22/14-30/abc123def456 --round 3
```

## 3. 各命令细节

### `doctor`

对 `claude` / `codex` 各跑一次 `--version` 检查退出码，任一失败即该行打印 `False`。用于环境自检。

### `start`

最简用法。流程：建 Run → 建 run 目录 → 循环状态机跑完全部轮次 → 打印最终状态（`COMPLETE/FAILED/ABORTED`）+ 报告路径。全程无交互；进程被杀或超时由内部 `cancel_event` / 超时机制兜底。

轮次按阶段推进：第 1 轮只做信息收集（镜像/指纹/端点清单），第 2 轮由规划器定方向并开跑利用任务，之后轮次聚焦深化利用（详见 [rounds.md](rounds.md)）。正常节奏约 3~5 轮。

### `tui`

交互式界面，核心价值是**实时看 Claude 规划思考**和 **Codex 任务进展**：

- 启动后先输入 `goal>` 目标，回车即开始跑（后台线程），主界面持续流式输出。
- 命令行支持：

| 命令 | 说明 |
|---|---|
| `status` | 打印 `run.json` 当前状态 |
| `tasks` | 列出 `tasks/` 下所有结果文件 |
| `findings` | 列出 `findings/` 目录文件（⚠️ 当前恒空，见 [known-gaps](known-gaps.md)） |
| `logs` | 列出本轮产生的 `claude_round_*.jsonl` |
| `claude [round]` | 回放指定轮（或最新一轮）的 claude 日志 |
| `abort` | 请求优雅中断（置 abort 信号，杀子进程） |
| `quit` / `exit` | 中断并退出 |

- 输出组件着色：`CLAUDE`（顶层）/ `CLAUDE-PLAN-*`（规划子代理）/ `CODEX-*`（执行）/ `ORCH` / `ERROR`。
- TUI 会把全量输出同步转写到项目根 `tui.log.txt`，非 TTY 时流式输出自动退化为整行日志。

### `resume`

针对中断过的 run：`vulnhunt resume <run_dir>` 重建 store 与 orchestrator，从磁盘 `run.json` 的当前状态继续 `run_loop()`。适用于 `start` 被 Ctrl+C、进程崩溃、超时等情况后的续跑。注意：RUNNING 中断会**重跑整轮**当前 plan（不会跳过已完成任务，见 [known-gaps](known-gaps.md) 缺口 9）。

### `log`

纯离线工具，不跑任务。定位：复盘某轮 Claude 到底怎么规划的。不带 `--round` 时回放最新的 `claude_round_*.jsonl`；`--round N` 回放第 N 轮。Windows 下会先 `sys.stdout.reconfigure(utf-8)` 保证中文不乱码。

## 4. 运行产物目录结构

一次 run 落盘在 `runs_root/<年>/<月>/<日>/<时-分>/<run_id>/`（`runs_root` 默认 `vulnhunt-runs`）：

```
vulnhunt-runs/2026/08/22/14-30/abc123def456/
├── run.json              # Run 状态（goal/status/current_round/max_rounds/...）
├── state.json            # 当前状态快照 {status, round}
├── CLAUDE.md             # 自动从项目根复制（授权范围/漏洞清单上下文）
├── plans/round_001_plan.json     # 每轮 Claude 规划的任务列表
├── tasks/round_001_task_1_input.json   # 发给 codex 的任务输入
├── tasks/round_001_task_1_result.json  # codex 返回结果（status/summary/findings/...）
├── findings/             # ⚠️ 目录恒空：save_finding() 从未被调用（见 known-gaps）
├── blackboard/           # codex 共享黑板目录（所有 codex 共享、跨轮保留）
├── logs/claude_round_001.jsonl   # claude 每轮 stream-json 原始日志
├── logs/codex_task_1.jsonl       # codex 每任务日志
├── report/report.json    # 聚合 run + 全部 task 结果
├── report/report.md      # 极简报告（仅一行一条 task_id: summary）
└── workspaces/round_001_task_1/  # 每个 codex 任务独立工作目录
    ├── _last_message.json        # codex 写回的 JSON 结果
    └── .codex_session            # codex 会话 id（续跑用）
```

所有写入均为原子操作（先写 `.tmp` 再 `os.replace`），崩溃中断不会留半截文件。TUI 模式还会额外生成项目根的 `tui.log.txt` 全量转写。

## 5. 安全注意事项

- **仅对授权范围（`*.imou.com`）使用**。工具会向目标发送主动请求，且规划目标含"账号、验证码爆破"类任务，无授权使用可能违法。
- 顶层 Claude 以 `--permission-mode bypassPermissions` 运行、codex 以 `-s danger-full-access` 沙箱运行，**请勿在目标之外的环境中误触发**。
- Codex 任务 prompt 严格限制只写本任务 workspace 与共享黑板目录（禁止 `..` / 绝对路径绕过），但这是**提示词约束而非强隔离**——若信任边界敏感，需额外加固。
- 真实 CLI 测试（`VULNHUNT_REAL_TESTS=1`）会真实调用模型并可能发请求，谨慎开启。
- `workspaces/`、`logs/` 与 `blackboard/` 里可能残留 codex 抓取的页面、响应、token 类中间数据；黑板内容跨轮保留，交付/归档前请一并清理。
