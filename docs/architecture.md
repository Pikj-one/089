# vulnhunt 深度架构设计

> 源码级剖析。目标读者：要读懂/改动这个框架的人。所有机制均对照 `src/vulnhunt/` 源码核实。

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

## 3. PLANNING 深层机制（`src/vulnhunt/cli/claude_code.py`）

主 agent 直连规划：喂提示词 → 收集完整 stdout → 从 result envelope 取规划 JSON → `compute_orders()` 确定性排序。

### 3.1 调用形态

```python
claude -p "" --output-format stream-json --include-partial-messages --verbose \
       --permission-mode bypassPermissions (--session-id <uuid> | --resume <uuid>)
```

- `-p` + stdin 传入 `planner_prompt()`（见 3.3）。
- `--output-format stream-json`：每行一个 JSON 事件，供实时解析与日志回放。
- `--permission-mode bypassPermissions`：允许 Claude 读 run 目录里的 CLAUDE.md 等文件而不弹权限。**permission mode 不随会话继承**（2026-08-24 CLI 实测）：resume 恢复上下文记忆（`usage.cache_read_input_tokens` 可见整段历史被加载），但不恢复 bypassPermissions——resume 不传 `--permission-mode` 时回落默认权限（`-p` 非交互无法弹授权，连读 run 目录文件都被拒）。因此**每轮（含 resume）都必须显式传 `--permission-mode bypassPermissions`**，与 codex 侧 `resume` 不继承 `sandbox_policy` 的行为一致（见 §4.3）。
- 第 1 轮 `--session-id <uuid>` 新建会话；第 2 轮起改用 `--resume <uuid>` 续接同一会话（跨轮上下文延续，同一大脑延续历史）。注意 `--session-id` 的语义是「新建指定 ID 的会话」，对已落盘的 ID 会报 `already in use` 启动即退——续接必须用 `--resume`（2026-08-24 实测确认）。若续接的子进程仍启动即退，`plan()` 自动放弃旧会话、换全新会话重试一次——主 agent 直连后规划状态全在 prior+黑板里，换会话零损失。

### 3.2 结果解析

进程结束后从 stdout 反序遍历找 `type == "result"` 的 envelope，取 `result.text` 作为规划输出；再做清洗：

- 去掉 ```` ```json ```` 围栏（`removeprefix/removesuffix`）；
- 若 raw 以 `{` 开头且含 `\n{`，**只取最后一行**（防模型把解释文字和 JSON 混在一行）；
- `json.loads` 失败即抛异常 → 整个 run 标记 FAILED。

解析出的 tasks 随即过 `models.compute_orders()`：order 由代码按 `depends_on` 计算（无依赖/悬空引用→0，否则 1+max(有效依赖)，环上任务→0），计算后清空 `depends_on` 再落盘——模型只负责声明依赖，排序永远确定性。stream-json 的逐行事件仍实时喂给 `logview.ClaudeLogRenderer` 做 TUI 渲染（thinking/tool 流高亮），但不再做任何 subagent 拼装捕获（那是旧两层架构的需求）。

### 3.3 提示词（`src/vulnhunt/prompts.py`）

`planner_prompt(goal, round_no, prior, workspace_root, max_workers=10, blackboard_dir="")` 单层直连，结构：

- **角色**：规划大脑。每轮拆任务列表（JSON），执行交给 codex。
- **项目上下文**：授权范围与垃圾漏洞清单由模型自行读取当前目录（run 目录）的 CLAUDE.md（依赖 `RunStore.create()` 复制项目根 CLAUDE.md 进 run 目录的行为）；目标 / 当前轮次 / 上轮结果（prior 经 `slim_prior()` 剥掉 stdout_tail/stderr_tail 后 JSON 序列化注入——规划决策只需 status/summary/findings 与证据路径，裸输出尾部是纯噪音且一旦进入续接会话历史就每轮重放）；共享黑板路径；并发上限 `max_workers`。
- **输出契约**：纯英文 JSON `{"tasks":[{id,title,description,required_output?,relevant_context?,depends_on?}]}`；不输出 order（系统按 depends_on 计算）。
- **规划约束**：depends_on 只引用本轮任务 id、只标直接依赖；去重规划（镜像任务写黑板、分析任务 depends_on 它）；一个任务一个方向，过重必须拆分。
- **轮次阶段**：第 1 轮 = 信息收集轮（严禁漏洞探测类任务，首个任务必须是站点镜像写黑板）；第 2 轮 = 方向规划轮（基于黑板产物定 5~8 个方向直接开任务）；第 3 轮起 = 利用深化轮（每轮 1~3 个方向）。

### 3.4 日志

每轮 claude 的 stream-json 逐行追加到 `logs/claude_round_<NNN>.jsonl`（原文保留，供 `vulnhunt log` 回放）。解析动作通过 `logger/streamer/stream_end` 回调输出到 TUI 或静默丢弃。

## 4. RUNNING 深层机制（`src/vulnhunt/workers.py` + `cli/codex.py`）

### 4.1 并发模型

`WorkerPool.run(tasks, round_no)`：

```python
with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
    return list(pool.map(one, tasks))
```

- 保留任务按 `order` 升序**稳定排序**后分组：同一 order 一波，波内 `ThreadPoolExecutor(max_workers)` 并行；`pool.map` 返回即本波全部完成，形成**波间同步屏障**，后一波才启动。结果按波次顺序拼接（波内保序）。
- **超出 `max_workers` 的 task 直接丢弃**——只执行前 `max_workers` 个，不排队；被丢弃的任务 ID 记录在 `logs/round_<NNN>.log`，供下一轮重新规划。
- 每个 task 的 workspace：`<run_dir>/workspaces/round_<NNN>_<task_id>/`，`exec_task` 内 `mkdir`。
- 任务输入先落盘 `tasks/<tid>_input.json`；结果由 `exec_task` 返回后落盘 `tasks/<tid>_result.json`。

### 4.2 Codex 调用形态

```python
codex exec "" -C <workspace> --add-dir <blackboard> --json -o <workspace>/_last_message.json \
      -s danger-full-access --skip-git-repo-check --color never
```

- `-C <workspace>`：工作目录（先 `Path(workspace).resolve()` 固定为绝对路径，避免 Windows 下 cwd 相对嵌套成 `runs\...\workspaces\...` 的 os error 3）。
- `--add-dir <blackboard>`：开放 `<run_dir>/blackboard/` 作为共享黑板目录（所有 codex 共享、跨轮保留）。该目录会随会话写入 `session_meta.workspace_roots`，但实测（0.149.0）**resume 不恢复会话的 `sandbox_policy`**——它回落默认沙箱（cwd=workspace 时 `workspace-write`、共享黑板被拒写；cwd 在其他目录时甚至只读），`session_meta` 里的 `workspace_roots`/`sandbox_policy` 并不会让黑板恢复可写。因此 resume 分支必须显式传 `--dangerously-bypass-approvals-and-sandbox` 获得与 fresh 分支 `danger-full-access` 等价的全权访问（2026-08-24 实测：不加此 flag 黑板写入被拒，加了即可写）。
- `-s danger-full-access`：完整沙箱权限（执行命令、读写文件、联网）。**这是强沙箱声明，请只对授权目标使用**。
- `--json -o _last_message.json`：codex 把最终回复写成 JSON 文件，vulnhunt 再轮询读取。
- 任务提示词（模板内嵌）严格约束：
  - 要求输出 `status`（SUCCESS/FAILURE/PARTIAL）+ `summary` + `findings` 的**纯 JSON**；
  - **共享黑板契约**：可写入黑板的共享资源为页面 HTML、JS 源码/提取产物、robots.txt、API 文档/响应提取物（JSON/文本）与派生中间结果（端点清单、指纹报告、路由/账号清单等），命名规范 `<工作目录名>_<原文件名>`（如 `round_001_task_2_umi.js`）；**禁止写入** CSS、图片、字体、原始 HTTP 响应头 dump（噪音资产，留在 workspace 即可）；**下载前先查黑板**，已有同名/同 URL 资源直接复用、禁止重复下载；私有产物（脚本、临时文件、最终 JSON 报告、截图）只写本任务 workspace；
  - 路径限制：本任务只允许访问 workspace 与共享黑板目录，禁止 `..`、绝对路径、访问 tasks/logs/findings/report/其他任务目录；
  - "任务完成时结束所有产生的子进程"。
- codex 任务结束后（无论成败），`exec_task` 对黑板执行两道后处理（`src/vulnhunt/blackboard.py`）：`sanitize_blackboard()` 按后缀+内容启发式删除 CSS/图片/字体/响应头 dump 噪音文件；`format_blackboard_js()` 对未压缩的小型 .js 用 Prettier 静默格式化（跳过 >1MB 或平均行长 >2000 的压缩产物，失败静默忽略）。

### 4.3 会话续跑

- `exec_task` 先查 workspace 里是否有 `.codex_session`：有则走 `codex exec resume <id> - ...`（同一会话继续，保留历史上下文）。
- 首次运行：从 stdout 里找 `type == "thread.started"` 事件，取 `thread_id` 写入 `.codex_session`。
- 效果：同一 task 跨轮/断点续跑时，Codex 还记得上一轮的思考，而不是从头再来。
- 沙箱不继承：实测 `codex exec resume` 不会恢复会话记录的 `sandbox_policy`（`session_meta` 存了 `danger-full-access`，resume 仍回落默认沙箱），且 resume 不接受 `-s`/`--add-dir`。因此 resume 分支显式传 `--dangerously-bypass-approvals-and-sandbox` 取得全权沙箱（`codex.py:71`），黑板与工作目录才能读写——**勿误以为配置随会话继承而省略该 flag**。
- 选项集差异：`codex exec resume` 的选项集比 `exec` 更小——不接受 `--color`（报 `unexpected argument`）、`--add-dir`、`-s`，沙箱相关仅 `--dangerously-bypass-approvals-and-sandbox`。全权沙箱只能靠该 flag（见上一条）；**勿给 resume 分支补 `--color never` 等 exec-only 标志**。

### 4.4 结果读取

`_last_message.json` 有内容后 `json.loads` 转 `WorkerResult`（字段见 `models.py`）；若 20 次轮询（每次 50ms）仍无内容，则构造一个 `FAILURE` 的 `WorkerResult`（带 `stdout_tail/stderr_tail/error`）返回，不抛异常——失败被记录，不拖垮整轮。

## 5. 进程管理（`src/vulnhunt/cli/base.py`）

`run_process()` 是唯一子进程入口，统一处理：

- **双读线程**：stdout / stderr 各起一个线程逐行读，避免管道填满死锁；`on_stdout_line` 回调支持逐行实时处理（claude 日志就是靠它）。
- **cancel 检查**：主循环 50ms 轮询 `cancel_event`，置位则强杀。
- **超时**：`deadline = start + timeout_s`；到点 `_kill_process()`，置 `timed_out=True`。
- **强杀跨平台**：Windows 用 `taskkill /pid <pid> /T /F`（杀整棵进程树，codex 派生的子进程也会被带走）；POSIX 先 `terminate()` 再 `kill()`。
- **编码**：统一 `utf-8 errors=replace`，Windows 控制台乱码不致命。
- **异常**：`OSError`（可执行文件不存在、stdin 管道破裂等）返回 `exit_code=-1`，并保留子进程已打印的 stderr——否则 claude/codex 启动即退关闭 stdin 时，真实报错会被吞成干巴巴的 `[Errno 32] Broken pipe`（见 [troubleshooting.md](troubleshooting.md) §2）。

## 6. 落盘协议（`src/vulnhunt/state.py`）

`RunStore` 是一层薄封装，核心两个设计：

### 6.1 原子写

```python
def _write(self, name, obj):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(...)
    os.replace(tmp, path)   # 原子替换
```

先写 `.tmp` 再 `os.replace`，崩溃不会留下半截 JSON。

### 6.2 目录布局与上下文复制

```
<run_dir>/
├── run.json / state.json        # 运行状态（原子写）
├── CLAUDE.md                    # RunStore.create() 时从项目根 shutil.copy2
├── plans/round_<NNN>_plan.json  # 每轮规划
├── tasks/<tid>_input.json       # 任务输入
├── tasks/<tid>_result.json      # 任务结果（WorkerResult 序列化）
├── findings/                    # ⚠️ 目录恒空，save_finding() 无调用点
├── blackboard/                  # codex 共享黑板目录（跨轮、跨 codex 保留）
├── logs/claude_round_<NNN>.jsonl / codex_<tid>.jsonl
├── report/report.json / report.md
└── workspaces/round_<NNN>_<tid>/   # codex 独立工作目录（含 _last_message.json / .codex_session）
```

序列化统一走 `models._plain()`：把 dataclass / Enum / list / dict 全部降为纯 JSON 类型。

## 7. 日志体系（`src/vulnhunt/logview.py`）

- **三层动作**：`LogAction`（整行）、`StreamAction`（流式增量）、`StreamEndAction`（结束当前流式行）。TUI 与 `AggregateSink`（回放）都消费这层抽象。
- **截断策略**（常量）：tool 结果 2000 字符/30 行、tool 输入 500、思考 2000、文本 4000、最终结果 500——长输出不会刷爆界面。
- **`is_plan_stream()`**：命中 `subagent_type=="Plan"` 或 `parent_tool_use_id ∈ plan_tool_ids` 的行按"规划"组件高亮。旧两层架构的产物，生产路径已不再传入 plan_tool_ids（主 agent 直连后无 subagent），保留仅供 `vulnhunt log` 回放历史 run 的旧日志。
- **回放**：`vulnhunt log <run_dir> [--round N]` → `replay_file()` 重新喂给 `ClaudeLogRenderer`，重现当时界面。

## 8. 关键设计权衡

| 决策 | 理由 | 代价 |
|---|---|---|
| 子进程而非 in-process 调用 LLM | 隔离、可强杀、复用成熟 CLI | 协议对接复杂（stream-json 解析） |
| Codex 任务间通过黑板共享中间结果 + order 分波 | 复用公共资源/中间结果、跨轮保留；同轮跨波次依赖可靠 | 同 order 并行写黑板仍有竞态，共享区靠提示词约束 |
| Claude 会话跨轮续接（首轮 `--session-id` 新建，之后 `--resume`） | 跨轮延续规划上下文 | 长 run 上下文成本持续累积（主 agent 直连 + prior 瘦身已把每轮净沉淀压到最小） |
| 每任务独立 workspace + 会话续跑 | 断点续跑、故障隔离 | 磁盘占用、需要 .codex_session 机制 |
| 纯 stdlib、零依赖 | 部署即用、无供应链面 | 一切轮子自己造（TUI、渲染、并发） |
| findings 独立落盘方法存在但未接 | 预留扩展（见 known-gaps） | 实际 findings 只藏在 task 结果里 |
