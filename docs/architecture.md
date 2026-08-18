# 架构与联调说明

## 为什么采用三角色

Claude Code 适合理解目标并拆分审计面，Codex CLI 适合在自身 sandbox 中执行具体任务，Orchestrator 则只管理生命周期和证据链。这样可以把规划、执行和状态控制分开，避免把完成判断完全交给任一 CLI。

主流程如下：

```text
用户目标
  -> Claude 生成 Plan
  -> WorkerPool 并发派发 Codex 任务
  -> 结果写入 runs/<run_id>/tasks/
  -> 下一轮 Planner 获取历史结果
  -> 生成 report/report.{md,json}
```

## 持久化约束

`RunStore` 使用临时文件加 `os.replace` 写入 JSON，避免进程中断时直接覆盖正式文件。任务结果按 task id 独立落盘，worker 不共享写入 `state.json`；状态快照由 Orchestrator 更新。

`runs/` 是运行时证据，不进入 Git。需要复盘时保留完整的 `run.json`、`state.json`、计划、任务结果和报告。

## CLI 联调

先使用 dry-run 验证编排链路：

```powershell
$env:PYTHONPATH = "src"
python -m vulnhunt start "审计目标"
```

再执行：

```powershell
python -m vulnhunt doctor
```

确认两个 CLI 都能返回版本后，将 `dry_run` 改为 `false`，先用小目标、低 `max_rounds` 和低并发做真实联调。

Windows 下优先配置 native `.exe`。超时处理依赖 `taskkill /T /F` 清理子进程树；如果本机没有该命令，应先修复运行环境，而不是把超时当作普通任务失败。

## 结果处理

Codex 的最终结果文件是任务 workspace 下的 `_last_message.json`；事件流只用于过程输出。这样可以避免依赖 JSONL 事件顺序。报告由落盘结果重新聚合生成，重启后仍可依据文件恢复审计证据。

## 版本与提交

项目采用 SemVer。提交信息使用 Conventional Commits，例如：

```text
feat(orchestrator): 支持多轮任务调度
fix(state): 修复结果文件原子写入
docs(readme): 更新真实 CLI 联调说明
```

提交前至少运行单元测试、编译检查和 `git diff --check`。
