# VulnHunt

VulnHunt 是一个纯 Python 标准库实现的漏洞挖掘编排 MVP：Claude Code 负责生成审计计划，Codex CLI 并发执行子任务，Orchestrator 负责轮次、状态持久化和报告生成。

## 当前能力

- 纯标准库，无运行时第三方依赖
- `dry_run` 模式可在不调用外部 CLI 的情况下验证完整流程
- 提供交互式 `tui` 入口，可查看运行状态、任务文件和发现文件
- Claude/Codex 子进程通过 stdin 接收任务，支持 Windows 超时进程树清理
- 每次运行保存计划、任务输入、任务结果、状态快照和报告
- 支持 `start`、`resume`、`doctor` 命令

## 环境

- Python 3.11+
- 使用真实流程时，需要可执行的 Claude Code CLI 和 Codex CLI
- Windows 下建议在 `config.toml` 中填写 native `.exe` 路径

## 快速开始

项目根目录执行：

```powershell
$env:PYTHONPATH = "src"
python -m vulnhunt start "审计 demo/target.py 是否存在路径穿越"
```

默认配置启用 `dry_run = true`，运行结束后会在 `runs/<年>/<月>/<日>/<时>-<分>-<run_id>/report/` 生成 `report.md` 和 `report.json`。

也可以安装本地命令：

```powershell
python -m pip install -e .
vulnhunt start "审计目标目录"
```

## 配置真实 CLI

如果 `claude` 和 `codex` 已加入系统 PATH，只需修改开关：

```toml
claude_exec = "claude"
codex_exec = "codex"
target_dir = "."
dry_run = false
max_rounds = 2
max_workers = 3
```

也可以通过全局环境变量覆盖：

```powershell
$env:VULNHUNT_CLAUDE_EXEC = "claude"
$env:VULNHUNT_CODEX_EXEC = "codex"
$env:VULNHUNT_DRY_RUN = "false"
```

启动前可以检查 CLI：

```powershell
python -m vulnhunt doctor
```

环境变量 `VULNHUNT_<字段名大写>` 可以覆盖配置文件，例如 `VULNHUNT_DRY_RUN=false`。

## 恢复与证据

运行目录采用以下布局：

```text
runs/<年>/<月>/<日>/<时>-<分>-<run_id>/
├── run.json
├── state.json
├── plans/
├── tasks/
├── workspaces/
├── findings/
├── logs/
└── report/
```

恢复已有运行：

```powershell
python -m vulnhunt resume runs/<年>/<月>/<日>/<时>-<分>-<run_id>
```

`runs/` 默认被 Git 忽略，适合保存本地运行证据，不会进入项目提交。

## 开发验证

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src
```

真实 CLI 测试默认跳过，避免意外消耗 token。确认本机 CLI、登录状态和权限后显式开启：

```powershell
$env:PYTHONPATH = "src"
$env:VULNHUNT_REAL_TESTS = "1"
python -m unittest tests.test_real_cli -v
```

真实测试会分别调用 Claude 生成最小 Plan、调用 Codex 生成最小结构化结果；通常比单元测试耗时更长。

## 交互式 TUI

启动 TUI 后先输入目标，随后使用 `>` 提示符输入命令：

```powershell
python -m vulnhunt tui
```

支持 `status`、`tasks`、`findings`、`abort` 和 `quit`。TUI 当前是纯 stdin/stdout 的 MVP，不提供全屏刷新或 ANSI 面板。

## 设计说明

架构决策、Windows CLI 进程约束、结果权威源和后续联调注意事项见 [docs/architecture.md](docs/architecture.md)。

## 当前限制

当前版本是 MVP：TUI 仅提供基础日志 facade，恢复流程和完成判定仍在持续增强；真实 CLI 联调需要本机分别验证 Claude Code 与 Codex 的版本、权限和 sandbox 配置。
