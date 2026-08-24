# vulnhunt 深度架构设计

> 源码级剖析。目标读者：要读懂/改动这个框架的人。所有机制均对照 `src/vulnhunt/` 源码核实。
> 本文是架构骨架（总体设计 / 状态机 / 关键设计权衡）+ 文档导航；每个子系统的源码级深层机制已拆分到独立文件（见 §3）。

## 1. 总体设计

vulnhunt 是一个 **编排框架**，本身不发任何 HTTP 请求、不做任何漏洞检测——真正的"活"全由外部两个 LLM CLI 干：

- **Claude（大脑）**：负责规划。每轮读取目标、上轮结果，拆出下一步该做什么，输出结构化任务列表。
- **Codex（手）**：负责执行。每个任务对应一个独立 Codex 实例，在隔离工作目录里完成审计/探测，返回结构化结果。

vulnhunt 在中间只做三件事：**组装上下文 → 调度子进程 → 持久化结果**。它刻意保持零第三方依赖（纯 stdlib），把复杂度集中在"跟两个 CLI 的协议对接"上。

```
                    ┌─────────────────────────── vulnhunt ───────────────────────────┐
  目标 + 上轮结果      │  prompts.py(模板)   orchestrator.py(状态机)   state.py(落盘)     │
──► Claude（大脑）────►  JSON tasks（depends_on）── compute_orders() ──► WorkerPool ──►  Codex x N ──► 结果文件
                                                            (线程池)      (独立 workspace)    │
                                                                                              ▼
                                                                        report.py ◄── tasks/*_result.json
```

### 为什么是"单一大脑 + 多手"直连架构？

- **上下文隔离**：每个 Codex 实例不共享任何信息，任务之间天然并行且互不污染，避免一个长会话上下文膨胀失控。
- **规划收敛**：Claude 大脑汇总所有手的结果后统一决策，保证攻击面覆盖有全局视角。
- **进程级故障隔离**：Codex 崩了不影响其他手，也不影响规划进程；Claude 会话跨轮 resume 续上下文。
- **无中转层**（2026-08-24 重构）：曾有「顶层 Claude → Plan subagent」两层结构——顶层负责转发提示词与计算 order。实测发现转发段要在顶层上下文里存两份、且随每轮 resume 永久重放，是多轮规划上下文膨胀的最大源头；而 order 计算本就是确定性算法、占位符补全只是读文件，都不需要 LLM。现改为主 agent 直连规划：order 由 `models.compute_orders()` 代码计算，授权范围/垃圾清单由模型自行读取 run 目录 CLAUDE.md，prior 注入前剥掉 stdout/stderr 噪音——每轮净沉淀只剩规划器自己的思考与任务 JSON，上下文按构造有界。

### 一次 run 的完整时序

```
start (main.py)
  └─ 建 Run + RunStore.create()           # 目录 vulnhunt-runs/<年>/<月>/<日>/<时-分>/<run_id>/
  │                                         # 复制项目根 CLAUDE.md 进 run 目录（授权上下文）
  └─ Orchestrator.run_loop()  循环 step()
       ├─ INIT        round=1 → PLANNING
       ├─ PLANNING    ClaudeWrapper.plan()：调 `claude -p`，喂 planner_prompt()
       │                ├─ 主 agent 直接规划，输出 JSON tasks（含 depends_on；授权范围/垃圾清单由模型读 run 目录 CLAUDE.md）
       │                ├─ compute_orders() 按依赖算 order，清空 depends_on 后存盘
       │                └─ 存 plans/round_NNN_plan.json
       ├─ DISPATCHING → RUNNING
        ├─ RUNNING      WorkerPool：按 order 分波执行（同波 ThreadPoolExecutor 并行）
       │                ├─ 每任务一个 workspaces/round_NNN_<taskid>/ 目录
       │                ├─ CodexWrapper.exec_task()：`codex exec -C <workspace> ...`
       │                ├─ codex 写回 _last_message.json（status/summary/findings）
       │                ├─ 结果读回 → WorkerResult → tasks/<tid>_result.json
       │                └─ .codex_session 存会话 id，供下轮 resume
       ├─ COLLECTING → DECISION
       └─ DECISION     若 current_round >= max_rounds → COMPLETE
                       否则 round+1 → PLANNING（上轮结果作为 prior 回填）
  结束 → build_report() 生成 report.json / report.md
```

## 2. 状态机（`src/vulnhunt/orchestrator.py`）

`Orchestrator.run_loop()` 是一个 while 循环，直到状态为 `COMPLETE / FAILED / ABORTED` 才停；`step()` 单步推进：

| 状态 | step() 内做的事 | 结果 |
|---|---|---|
| `INIT` | `current_round=1` | → `PLANNING` |
| `PLANNING` | `self.claude.plan(goal, round, prior, run_dir)` → 存 plan | → `DISPATCHING` |
| `DISPATCHING` | 无操作，仅状态推进 | → `RUNNING` |
| `RUNNING` | `WorkerPool(...).run(plan.tasks, round)`，结果存进 `self.prior` | → `COLLECTING` |
| `COLLECTING` | 无操作，仅状态推进 | → `DECISION` |
| `DECISION` | `round >= max_rounds` ? 结束 : `round+1` | → `COMPLETE` 或 → `PLANNING` |
| 终态 | `COMPLETE / FAILED / ABORTED` | 循环退出 |

每步结束都 `save()`（`run.json` + `state.json`），所以**任意时刻崩溃都能从磁盘状态续跑**。

### 中断与异常归因

- `self._abort = threading.Event()`：挂到 claude/codex 的 `cancel_event`，子进程循环轮询后强杀；也用于 TUI 的 `abort` 命令。
- `KeyboardInterrupt` → `ABORTED`（用户主动）。
- 其他异常 → 若 `_abort.is_set()` 归为 `ABORTED`，否则 `FAILED`。

### resume 机制

`vulnhunt resume <run_dir>` 直接 `RunStore(run_dir)` 重建 store，`Orchestrator.__init__` 若 `run.current_round` 已有 plan 则从磁盘重建 `self.plan`，`run_loop()` 从当前状态继续。中断在 RUNNING 中途时，已完成的任务结果已在 `tasks/` 落盘，重新 `run()` 会重跑本轮的 plan（先读磁盘结果再决定？否——**重跑整轮**，见 `known-gaps.md` 缺口 9 的说明）。

## 3. 深层机制拆解

以下是原 architecture.md 各子系统章节的独立拆分，每篇独立成文、章节号重排；阅读时按子系统取用：

| 文件 | 覆盖子系统 | 章节内容 |
|---|---|---|
| [architecture-planning.md](architecture-planning.md) | Claude 规划大脑：`cli/claude_code.py` + `prompts.py` | §1.1 调用形态（首轮/续接双命令）、§1.2 结果解析、§1.3 提示词、§1.4 日志 |
| [architecture-execution.md](architecture-execution.md) | Codex 执行 + 进程管理：`workers.py` + `cli/codex.py` + `cli/base.py` | §1.1 并发模型、§1.2 codex 调用形态、§1.3 会话续跑（resume 命令）、§1.4 结果读取、§2 run_process |
| [architecture-state.md](architecture-state.md) | 落盘与日志：`state.py` + `logview.py` | §1.1 原子写、§1.2 目录布局与上下文复制、§2 日志体系 |

## 4. 关键设计权衡

| 决策 | 理由 | 代价 |
|---|---|---|
| 子进程而非 in-process 调用 LLM | 隔离、可强杀、复用成熟 CLI | 协议对接复杂（stream-json 解析） |
| Codex 任务间通过黑板共享中间结果 + order 分波 | 复用公共资源/中间结果、跨轮保留；同轮跨波次依赖可靠 | 同 order 并行写黑板仍有竞态，共享区靠提示词约束 |
| Claude 会话跨轮续接（首轮 `--session-id` 新建，之后 `--resume`） | 跨轮延续规划上下文 | 长 run 上下文成本持续累积（主 agent 直连 + prior 瘦身已把每轮净沉淀压到最小） |
| 每任务独立 workspace + 会话续跑 | 断点续跑、故障隔离 | 磁盘占用、需要 .codex_session 机制 |
| 纯 stdlib、零依赖 | 部署即用、无供应链面 | 一切轮子自己造（TUI、渲染、并发） |
| findings 独立落盘方法存在但未接 | 预留扩展（见 known-gaps） | 实际 findings 只藏在 task 结果里 |
