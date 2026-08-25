# vulnhunt 开发 / 维护指南

> 面向要改代码的人。先读 [architecture.md](architecture.md) 建立全貌，再按子系统深入 [architecture-planning.md](architecture-planning.md)（规划）/ [architecture-execution.md](architecture-execution.md)（执行与进程）/ [architecture-state.md](architecture-state.md)（落盘与日志），最后对照本文件定位"改哪里"。

## 1. 环境搭建

```bash
pip install -e .                 # 开发安装（获得 vulnhunt 命令）
PYTHONPATH=src python -m unittest discover tests -v   # 跑测试
```

零第三方依赖，不需要装任何额外包。Python >= 3.11（用了 `str|None` 语法、`tomllib`）。

## 2. 文件 → 职责 → "改哪里"速查

| 想改的东西 | 对应文件 | 入口 |
|---|---|---|
| 新子命令 / CLI 参数 | `src/vulnhunt/main.py` | `main()` 里的 argparse |
| 状态机逻辑（加状态/改终局判定） | `src/vulnhunt/orchestrator.py` | `run_loop()` / `step()` |
| 给 Claude 的提示词 / 任务拆分规则 | `src/vulnhunt/prompts.py` | `planner_prompt()` |
| claude 调用参数（model、permission、超时） | `src/vulnhunt/cli/claude_code.py` | `plan()` 里的 args 列表 |
| codex 调用参数（沙箱、model、超时） | `src/vulnhunt/cli/codex.py` | `exec_task()` |
| 并发度 / 任务丢弃策略 | `src/vulnhunt/workers.py` | `WorkerPool.run()` |
| 数据模型（字段/枚举） | `src/vulnhunt/models.py` | 各 dataclass / StrEnum |
| 落盘布局 / 新增文件类型 | `src/vulnhunt/state.py` | `RunStore` |
| 报告格式 | `src/vulnhunt/report.py` | `build_report()` |
| TUI 命令 / 配色 / 交互 | `src/vulnhunt/tui.py` | `_handle_command()` / `_colors` |
| 日志渲染 / 截断 / 回放 | `src/vulnhunt/logview.py` | `ClaudeLogRenderer` / `truncate` |
| 子进程 / 超时 / 强杀 | `src/vulnhunt/cli/base.py` | `run_process()` / `_kill_process()` |
| 配置字段 | `src/vulnhunt/config.py` | `Config` dataclass + `load_config()` |
| JSON schema 校验 | `src/vulnhunt/schema.py` | 目前死代码（见 [known-gaps](known-gaps.md) 缺口 4） |

## 3. 常见开发任务操作指南

### 3.1 改"给 Claude 的提示词"

在 `planner_prompt()` 里改（单层直连，没有转发段）。注意三点契约：
1. Claude 输出必须是**纯 JSON** `{"tasks":[{...,depends_on}]}`，系统靠它解析；**不要让模型输出 order**——order 由 `models.compute_orders()` 按 depends_on 确定性计算；
2. 授权范围/垃圾漏洞清单不注入提示词，由模型自行读取 run 目录 CLAUDE.md（cwd 即 run 目录）；
3. 动态上下文一律用 Python 字符串插值（`{goal}`、`{round_no}`、`prior`、`{workspace_root}`、`{max_workers}`、`{blackboard}`），不要加占位符。

给 codex 的提示词在 `src/vulnhunt/cli/codex.py` 的 `exec_task()` 内拼装，含**共享黑板契约**：抓取的可复用原始资源/派生中间结果必须写黑板（命名 `<工作目录名>_<原文件名>`）、下载前先查黑板再复用、私有产物只写 workspace。改动时保持纯 JSON 输出契约（status/summary/findings）。

轮次阶段规则（信息收集轮 / 方向规划轮 / 利用深化轮）也在 `planner_prompt()` 内，改动时参考 [rounds.md](rounds.md) 保持三阶段约束一致。

### 3.2 加一个 TUI 命令

`tui.py` 的 `_handle_command()` 里加分支即可：
- 读文件类命令参考 `_show_json` / `_show_files`；
- 输出用 `self.log(component, message)`（组件名决定颜色，可在 `_colors` 注册新颜色）；
- 记得同时更新 `command_loop` 里"run finished"提示的命令列表文案。

### 3.3 改报告

`build_report()` 目前只有一行循环。要展开 findings/severity/evidence：
1. 从 `tasks/*_result.json` 的 `findings` 字段取证据（字段结构由 codex 决定，见 `codex.py` 提示词里的"必须包含 status、summary、findings"）；
2. 需要落盘到 `findings/` 就先接上 `RunStore.save_finding()`（见 [known-gaps](known-gaps.md) 缺口 2）；
3. 用 `models.Severity` 排序/分级。

### 3.4 加一个落盘文件类型

`state.py` 的 `RunStore` 加方法，模式照抄 `save_plan`/`save_task_result`：
```python
def save_xxx(self, ...):
    self._write('xxx/xxx.json', data)
```
`_write` 已保证原子写，直接用。

### 3.5 改状态机

`step()` 是单步推进，每一步末尾 `self.save()` + `self.store.save_state(...)` 已保证可恢复。加状态时：
- 在 `models.RunStatus` 加枚举值；
- 在 `step()` 加一个 `elif` 分支；
- 注意 `resume` 语义：RUNNING 中断会重跑整轮，若不想这样，在 WorkerPool 里先读磁盘结果。

### 3.6 给 claude / codex 传 model 参数

原 `claude_model` / `codex_model` 等未生效字段已删除（见 [known-gaps](known-gaps.md) 缺口 5）。若要支持：
1. 在 `config.py` 的 `Config` 重新添加字段（如 `claude_model: str=""`）；
2. claude：`claude_code.py` args 里加 `--model <config.claude_model>`（非空时）；
3. codex：`codex.py` args 里加 `--model <config.codex_model>`（非空时）；
4. 参考 codex CLI 的 `--model` 参数格式（`codex exec --help`）。

## 4. 测试规范

- 单测**不要**依赖真实 CLI：用 `tests/fakes.py` 的 `FakeClaude` / `FakeCodex` 桩。
- 新增会调真实 CLI 的用例，必须 `@unittest.skipUnless(os.getenv("VULNHUNT_REAL_TESTS")=="1", ...)` 门控（照抄 `test_real_cli.py`）。
- 涉及进程的用例参考 `test_base.py` 的 `holder` 模式（清理子进程，避免 Windows 残留）。
- 断言尽量用 roundtrip（`to_dict` → `from_dict`）验证序列化，参考 `test_models.py`。

## 5. 代码风格

- 现有代码是**紧凑风格**：一行多语句、类字段同一行逗号分隔、少空行。**新代码保持与所在文件一致的紧凑风格**，不要混入 PEP8 风格造成视觉割裂。
- 中文注释/日志已存在（如 `orchestrator.py`、`codex.py` 提示词），新增提示词与面向用户的日志可用中文；代码标识符用英文。
- 字符串用双引号（现有统一）。类型注解尽量写（Python 3.11+）。

## 6. 发布流程

1. 改 `pyproject.toml` 的 `version`（当前 0.10.0）；
2. 同步 `src/vulnhunt/__init__.py` 的 `__version__`；
3. 跑全量测试确认绿；
4. `pip install -e .` 本地验证新版本命令可用（如改了 CLI）；
5. 如需分发：`python -m build` + `twine upload`（当前无第三方依赖，产物很小）。

## 7. 优先修复建议（对齐 known-gaps）

按价值排序：**① findings 落盘 → ② 报告完善 → ③ resume 语义 → ④ 非 Windows 验证**。①②直接影响产出质量，③影响长 run 的可靠性，④是兼容性盲区。提示词对齐（缺口 6）与配置字段清理（缺口 5）已解决；每个的修复入口都在上文速查表与 [known-gaps.md](known-gaps.md) 中。
