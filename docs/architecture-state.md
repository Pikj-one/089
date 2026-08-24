# 落盘协议与日志体系（`src/vulnhunt/state.py` + `src/vulnhunt/logview.py`）

> 源码级剖析。主 hub 见 [architecture.md](architecture.md) §1~2（总体设计 / 状态机）。本文件是原 architecture.md §6、§7 的独立拆分，章节号已重排。

## 1. 落盘协议（`src/vulnhunt/state.py`）

`RunStore` 是一层薄封装，核心两个设计：

### 1.1 原子写

```python
def _write(self, name, obj):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(...)
    os.replace(tmp, path)   # 原子替换
```

先写 `.tmp` 再 `os.replace`，崩溃不会留下半截 JSON。

### 1.2 目录布局与上下文复制

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

## 2. 日志体系（`src/vulnhunt/logview.py`）

- **三层动作**：`LogAction`（整行）、`StreamAction`（流式增量）、`StreamEndAction`（结束当前流式行）。TUI 与 `AggregateSink`（回放）都消费这层抽象。
- **截断策略**（常量）：tool 结果 2000 字符/30 行、tool 输入 500、思考 2000、文本 4000、最终结果 500——长输出不会刷爆界面。
- **`is_plan_stream()`**：命中 `subagent_type=="Plan"` 或 `parent_tool_use_id ∈ plan_tool_ids` 的行按"规划"组件高亮。旧两层架构的产物，生产路径已不再传入 plan_tool_ids（主 agent 直连后无 subagent），保留仅供 `vulnhunt log` 回放历史 run 的旧日志。
- **回放**：`vulnhunt log <run_dir> [--round N]` → `replay_file()` 重新喂给 `ClaudeLogRenderer`，重现当时界面。
