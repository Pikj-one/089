# PLANNING 深层机制（`src/vulnhunt/cli/claude_code.py` + `src/vulnhunt/prompts.py`）

> 源码级剖析。主 hub 见 [architecture.md](architecture.md) §1~2（总体设计 / 状态机）。本文件是原 architecture.md §3 的独立拆分，章节号已重排；涉及跨子系统机制时给出链接。

## 1. PLANNING 深层机制

主 agent 直连规划：喂提示词 → 收集完整 stdout → 从 result envelope 取规划 JSON → `compute_orders()` 确定性排序。

### 1.1 调用形态

```python
# 首轮（新建会话）：--session-id <uuid>，uuid 由 vulnhunt 生成（claude_code.py:40）
claude -p "" --output-format stream-json --include-partial-messages --verbose \
       --permission-mode bypassPermissions --session-id <uuid>

# 第 2 轮起（续接同一会话）：--resume <uuid>；上下文跨进程继承，但 permission mode
# 不随会话继承——--permission-mode bypassPermissions 必须每轮显式传，否则回落默认权限
claude -p "" --output-format stream-json --include-partial-messages --verbose \
       --permission-mode bypassPermissions --resume <uuid>
```

- `-p` + stdin 传入 `planner_prompt()`（见 1.3）。
- `--output-format stream-json`：每行一个 JSON 事件，供实时解析与日志回放。
- `--permission-mode bypassPermissions`：允许 Claude 读 run 目录里的 CLAUDE.md 等文件而不弹权限。**permission mode 不随会话继承**（2026-08-24 CLI 实测）：resume 恢复上下文记忆（`usage.cache_read_input_tokens` 可见整段历史被加载），但不恢复 bypassPermissions——resume 不传 `--permission-mode` 时回落默认权限（`-p` 非交互无法弹授权，连读 run 目录文件都被拒）。因此**每轮（含 resume）都必须显式传 `--permission-mode bypassPermissions`**，与 codex 侧 `resume` 不继承 `sandbox_policy` 的行为一致（见 [architecture-execution.md](architecture-execution.md) §1.3）。
- 第 1 轮 `--session-id <uuid>` 新建会话；第 2 轮起改用 `--resume <uuid>` 续接同一会话（跨轮上下文延续，同一大脑延续历史）。注意 `--session-id` 的语义是「新建指定 ID 的会话」，对已落盘的 ID 会报 `already in use` 启动即退——续接必须用 `--resume`（2026-08-24 实测确认）。若续接的子进程仍启动即退，`plan()` 自动放弃旧会话、换全新会话重试一次——主 agent 直连后规划状态全在 prior+黑板里，换会话零损失。

### 1.2 结果解析

进程结束后从 stdout 反序遍历找 `type == "result"` 的 envelope，取 `result.text` 作为规划输出；再做清洗：

- 去掉 ```` ```json ```` 围栏（`removeprefix/removesuffix`）；
- 若 raw 以 `{` 开头且含 `\n{`，**只取最后一行**（防模型把解释文字和 JSON 混在一行）；
- `json.loads` 失败即抛异常 → 整个 run 标记 FAILED。

解析出的 tasks 随即过 `models.compute_orders()`：order 由代码按 `depends_on` 计算（无依赖/悬空引用→0，否则 1+max(有效依赖)，环上任务→0），计算后清空 `depends_on` 再落盘——模型只负责声明依赖，排序永远确定性。stream-json 的逐行事件仍实时喂给 `logview.ClaudeLogRenderer` 做 TUI 渲染（thinking/tool 流高亮），但不再做任何 subagent 拼装捕获（那是旧两层架构的需求）。

### 1.3 提示词（`src/vulnhunt/prompts.py`）

`planner_prompt(goal, round_no, prior, workspace_root, max_workers=10, blackboard_dir="")` 单层直连，结构：

- **角色**：规划大脑。每轮拆任务列表（JSON），执行交给 codex。
- **项目上下文**：授权范围与垃圾漏洞清单由模型自行读取当前目录（run 目录）的 CLAUDE.md（依赖 `RunStore.create()` 复制项目根 CLAUDE.md 进 run 目录的行为）；目标 / 当前轮次 / 上轮结果（prior 经 `slim_prior()` 剥掉 stdout_tail/stderr_tail 后 JSON 序列化注入——规划决策只需 status/summary/findings 与证据路径，裸输出尾部是纯噪音且一旦进入续接会话历史就每轮重放）；共享黑板路径；并发上限 `max_workers`。
- **输出契约**：纯英文 JSON `{"tasks":[{id,title,description,required_output?,relevant_context?,depends_on?}]}`；不输出 order（系统按 depends_on 计算）。
- **规划约束**：depends_on 只引用本轮任务 id、只标直接依赖；去重规划（镜像任务写黑板、分析任务 depends_on 它）；一个任务一个方向，过重必须拆分。
- **轮次阶段**：第 1 轮 = 信息收集轮（严禁漏洞探测类任务，首个任务必须是站点镜像写黑板）；第 2 轮 = 方向规划轮（基于黑板产物定 5~8 个方向直接开任务）；第 3 轮起 = 利用深化轮（每轮 1~3 个方向）。

### 1.4 日志

每轮 claude 的 stream-json 逐行追加到 `logs/claude_round_<NNN>.jsonl`（原文保留，供 `vulnhunt log` 回放）。解析动作通过 `logger/streamer/stream_end` 回调输出到 TUI 或静默丢弃。
