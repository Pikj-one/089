# vulnhunt 已知缺口 / 待办

> 接手时如实记录的问题，全部经过源码核实（`src/vulnhunt/`）。**建议先处理有 ⭐ 的条目再投入使用**。修复方向仅供参考，动手前先在 [development.md](development.md) 找对应位置。

## 1. ✅ 已实跑 — 链路端到端跑通（2026-08-23）

`../vulnhunt-runs` 已有两次真实 run（`2026/08/23/14-17`、`2026/08/23/15-00`）：Claude→Codex→黑板→报告链路跑通，产出真实 High/Medium 发现（未授权文件上传、设备 API 令牌门控绕过、预认证辅助接口、注册状态 oracle 等）。

**遗留问题**（详见 §10）：
- 三次 run（08-23 两 + 08-24 `10-35`）均在第 2 轮 PLANNING 崩溃，根因是续接既有会话时 claude 子进程启动即退、导致 stdin Broken pipe——已在 §10 复现并修复。
- 15-00 的 task_3 结果曾因 codex 在 JSON 前写解释文字导致解析失败、findings 全丢——已在 `codex.py` 用 `_extract_json` 修复。

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

`prompts.py` 曾写"超出十个的 task 会被系统默认丢弃不会排队"（重构后改为 f-string 注入实际 `max_workers`），此前 `workers.py` 用 `ThreadPoolExecutor` **把全部 task 排队执行完**（仅并发上限 max_workers）。

已实现丢弃（2026-08-23）：`WorkerPool.run()` 只取前 `max_workers` 个任务执行，超出的直接丢弃不排队，并写入 `logs/round_<NNN>.log` 记录被丢弃的任务 ID，便于追踪与下一轮重新规划。

同轮依赖语义（2026-08-23 更新）：原"同一轮任务禁止隐式依赖"规则已移除，改为 `order` 控制——Plan subagent 标注 `depends_on`、顶层 Claude 计算 `order`、`WorkerPool` 按 order 分波执行（同 order 并行、跨波次顺序执行）。整轮封顶仍在 order 分组之前生效，被丢弃任务若被其他任务 `depends_on`，其依赖方可能读到空黑板（已知边界）。

去重（2026-08-23）：同 order 并行任务若都抓取同一批基础资源（页面/JS 包）会各自重复下载——首波黑板为空，"先查黑板"无法避免，需规划侧先安排 order 最低的站点镜像任务写入黑板、分析任务 `depends_on` 它。这依赖模型自觉；若仍出现重复抓取，需在 `codex.py` 提示词或规划规则再强化。

## 7. ✅ 授权范围靠模型读 CLAUDE.md 而非硬编码 — 维持机制设计

授权范围与垃圾漏洞清单不注入提示词、不硬编码，由规划模型读取 run 目录复制的 `CLAUDE.md`（`RunStore.create()` 的复制行为是前提，claude 子进程 cwd 即 run 目录）。2026-08-24 架构重构时评估过"代码直读 CLAUDE.md 注入提示词"方案并实现过原型，按用户决定撤回——维持模型自行读取。风险同前：模型若不读文件则无授权约束，实跑日志显示各轮均会主动读取，暂不加代码层兜底。

## 8. Windows 兼容性依赖

进程树强杀依赖 `taskkill /T /F`；`codex.py` 有专门处理 Windows 路径嵌套 bug 的 `resolve()` 注释（相对 cwd 嵌套成 `runs\...\workspaces\...` 报 os error 3）。POSIX 侧的超时杀进程、TUI 非 TTY 回退等只在 Windows 上验证过。

**修复建议**：在 Linux/macOS 各跑一遍 `test_base.py` 与一次试运行，确认 `_kill_process` 的 POSIX 分支与 codex 参数在非 Windows 下正常。

## 9. resume 未验证

`resume` 命令与中断后续跑逻辑只有状态重建测试，真实运行风险未验证。注意语义：RUNNING 中断后 resume 会**重跑整轮当前 plan**（不会跳过已完成任务），`Workspace` 里已有 `.codex_session` 的任务会续跑会话，但本轮未完成任务的探测动作会重复执行。

**修复建议**：实跑一次中断→resume 全流程；如希望"跳过已完成任务"，需要在 WorkerPool 里先读磁盘已有的 `tasks/<tid>_result.json` 再决定是否重派。

## 10. ✅ codex 结果解析容错 + 轮次阶段提示词 — 已解决（2026-08-23）

- **codex 结果解析**：codex 会在 `_last_message.json` 的 JSON 前写解释文字（实测 `All work complete. Final report written to ...`），原 `json.loads(raw)` 直接失败 → 20 次轮询全败 → 任务被标 FAILURE、findings 全部丢失（一次真实 run 的 task_3 因此丢掉全部 High 发现）。已修复：`cli/codex.py` 新增 `_extract_json()`，取第一个 `{` 到最后一个 `}` 的子串再解析。
- **轮次阶段提示词**：`prompts.py` 新增「轮次阶段」规则——第 1 轮信息收集轮（严禁漏洞探测类任务）、第 2 轮方向规划轮（规划器直接定方向）、第 3 轮起利用深化轮（每轮 1~3 个方向）；禁止"测试所有漏洞类型"这类塞满全链路的巨型任务。
- **第 2 轮 PLANNING Broken pipe — 根因已确证并根治（2026-08-24）**：三次真实 run（08-23 两 + 08-24 `10-35`）全部在第 2 轮 PLANNING 崩溃。08-24 那次首次捕获异常（`logs/round_002.log` → `run failed: RuntimeError: [Errno 32] Broken pipe`）。完整链路：`plan()` 复用同一 `--session-id` 续接既有会话 → claude 子进程启动即退（零 stdout 输出、关闭 stdin）→ 父进程向 stdin 写提示词触发 `BrokenPipeError` → `cli/base.py` 的 `except OSError` 把子进程 stderr 整个丢弃、返回 `ProcResult(-1,'',str(e))` → `cli/claude_code.py` 据此 `raise RuntimeError("[Errno 32] Broken pipe")` → `run_loop` 标 FAILED。修复两处：① `cli/base.py` `run_process` 的 OSError 分支改为保留子进程已打印的 stderr；② `cli/claude_code.py` `plan()` 在"续接既有会话且非超时失败"时放弃旧会话、换全新会话重试一次（prior 已随提示词传入，规划上下文不丢）。**启动即退的根因当日确证**：`--session-id` 的语义是「新建指定 ID 的会话」，对已落盘的 ID 直接报 `Error: Session ID ... is already in use.` exit 1（实测复现）。此前兜底虽救回 run，但每轮都触发换新会话，跨轮上下文实际从未延续。根治：第 2 轮起改用 `--resume <id>` 续接（保持同一 session ID、上下文保留，实测验证）；resume 因其他原因失败时仍保留换新会话兜底。
- **两层规划架构移除 — 主 agent 直连（2026-08-24）**：旧「顶层 Claude → Plan subagent」结构下，转发段要在顶层上下文存两份（提示词 + Agent 工具入参）且随每轮 resume 永久重放，是多轮规划上下文膨胀的最大源头；而 order 计算本就是确定性算法、占位符补全只是读文件，都不需要 LLM。重构为单层直连：模型只输出带 `depends_on` 的 tasks JSON，order 由 `models.compute_orders()` 代码计算；授权范围/垃圾清单由模型自行读 run 目录 CLAUDE.md（占位符机制废除）；prior 注入前经 `slim_prior()` 剥掉 stdout_tail/stderr_tail。每轮净沉淀只剩规划器自身的思考与任务 JSON，上下文按构造有界。旧的 subagent JSON 流式捕获机器与 `planner_resume_prompt()` 一并删除；`logview.is_plan_stream()` 保留仅供旧日志回放。
