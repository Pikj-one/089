# vulnhunt 已知缺口 / 待办

> 接手时如实记录的问题，全部经过源码核实（`src/vulnhunt/`）。**建议先处理有 ⭐ 的条目再投入使用**。修复方向仅供参考，动手前先在 [development.md](development.md) 找对应位置。

## 1. ⭐ 从未实跑过 — 链路未端到端验证

仓库里没有 `../vulnhunt-runs` 目录，Claude→Codex→报告全链路没有一次真实运行记录。单测只验证了各模块自身。

**修复建议**：按 [usage.md](usage.md) 先 `doctor`，再以极小目标（如"检查 imou.com 首页安全头"）调低 `max_rounds`/`max_workers` 试跑一轮，验证产出完整（plans/tasks/logs/report 都有内容）。

## 2. ⭐ findings 不落盘

`RunStore.save_finding()`（`state.py:30`）全项目**无任何调用点**。Codex 返回的 `findings` 只存在于 `tasks/*_result.json`，`findings/` 目录永远为空；TUI 的 `findings` 命令也因此永远看不到东西。

**修复建议**：在 `orchestrator.py` 的 COLLECTING 阶段（或 `workers.py` 内）遍历 `WorkerResult.findings`，逐条 `store.save_finding(查找id, data)`；报告层再按 severity 汇总。

## 3. ⭐ 报告简陋

`report.py` 只聚合 `run.json` + `tasks/*_result.json`；`report.md` 仅一行一条 `task_id: summary`，不展开 findings、evidence_files、severity。

**修复建议**：`build_report()` 展开 `findings` 与 `evidence_files`，按 `Severity` 分级输出，md 版给每条 finding 加标题/证据/修复建议字段。

## 4. 死代码

- `schema.py` 的 `PLAN_SCHEMA_V1` / `TASK_RESULT_SCHEMA_V1` **从未被 import**（只有定义）。
- `models.CompletionDecision` 枚举**从未被使用**——`orchestrator.py` 直接用 `current_round >= max_rounds` 判断是否结束。

**修复建议**：要么接上（用 schema 校验 Plan/结果 JSON、用 CompletionDecision 统一终局判定），要么删除。

## 5. ✅ 配置字段大量未生效 — 已解决

未生效字段已全部删除（2026-08-23）：`plan_retry_max`、`claude_permission_mode`、`claude_model`、`codex_model`、`codex_approve_for_me`、`coverage_threshold`、`max_rounds_no_progress`、`verbose`、`target_dir`、`target_extra_dirs`（含 `Run.target_dir` 与 `config.toml` 中对应项）。现在 `Config` 保留的字段均为实际生效项（对照表见 [configuration.md](configuration.md) 第 3 节）。

**后续若需要** model/permission 模式、停滞检测、计划重试等能力：需重新添加字段并在调用点接线（claude 的 model/permission 参数、codex 的 model 参数、停滞检测、计划重试），入口见 [development.md](development.md)。

## 6. ✅ 提示词与实际行为不符 — 已解决

`prompts.py` 声称"超出十个的 task 会被系统默认丢弃不会排队"，此前 `workers.py` 用 `ThreadPoolExecutor` **把全部 task 排队执行完**（仅并发上限 max_workers）。

已实现丢弃（2026-08-23）：`WorkerPool.run()` 只取前 `max_workers` 个任务执行，超出的直接丢弃不排队，并写入 `logs/round_<NNN>.log` 记录被丢弃的任务 ID，便于追踪与下一轮重新规划。

同轮依赖语义（2026-08-23 更新）：原"同一轮任务禁止隐式依赖"规则已移除，改为 `order` 控制——Plan subagent 标注 `depends_on`、顶层 Claude 计算 `order`、`WorkerPool` 按 order 分波执行（同 order 并行、跨波次顺序执行）。整轮封顶仍在 order 分组之前生效，被丢弃任务若被其他任务 `depends_on`，其依赖方可能读到空黑板（已知边界）。

## 7. 授权范围是占位符而非硬编码

`prompts.py` 的 `授权范围：{{这里由你填写}}` 不硬编码 imou.com，靠运行时顶层 Claude 读取 run 目录复制的 `CLAUDE.md` 自行补全（`RunStore.create()` 的复制行为是前提）。

**修复建议**：这是机制设计而非 bug，但若想兜底，可在 `planner_prompt()` 里直接把 `CLAUDE.md` 的授权范围/清单内容填充进占位符（由代码注入而非依赖模型自觉）。

## 8. Windows 兼容性依赖

进程树强杀依赖 `taskkill /T /F`；`codex.py` 有专门处理 Windows 路径嵌套 bug 的 `resolve()` 注释（相对 cwd 嵌套成 `runs\...\workspaces\...` 报 os error 3）。POSIX 侧的超时杀进程、TUI 非 TTY 回退等只在 Windows 上验证过。

**修复建议**：在 Linux/macOS 各跑一遍 `test_base.py` 与一次试运行，确认 `_kill_process` 的 POSIX 分支与 codex 参数在非 Windows 下正常。

## 9. resume 未验证

`resume` 命令与中断后续跑逻辑只有状态重建测试，真实运行风险未验证。注意语义：RUNNING 中断后 resume 会**重跑整轮当前 plan**（不会跳过已完成任务），`Workspace` 里已有 `.codex_session` 的任务会续跑会话，但本轮未完成任务的探测动作会重复执行。

**修复建议**：实跑一次中断→resume 全流程；如希望"跳过已完成任务"，需要在 WorkerPool 里先读磁盘已有的 `tasks/<tid>_result.json` 再决定是否重派。
