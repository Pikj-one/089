# CLI JSON 流输出结构（Codex / Claude）

> 来源：按 vulnhunt wrapper 实际拼装的命令，对 `dome.py`（20 行 Pygame 心形动画脚本）做分析时的真实 JSONL 抓包。
> 环境：Termux / Codex CLI 当前版本 / Claude Code 2.1.234，模型均为 `deepseek-v4-flash`。
> 完整原始抓包：`docs/samples/vh_codex.jsonl`（10 行）、`docs/samples/vh_claude.jsonl`（2012 行，约 476 KB）、`docs/samples/vh_last_message.json`（codex 的 `-o` 文件）。

两个 CLI 输出都是 **JSONL**：每行一个 JSON 对象，逐行读取解析。

---

## 1. Codex（`codex exec --json`）

### 输入

wrapper 拼装的命令（`src/vulnhunt/cli/codex.py`）：

```bash
codex exec "分析 dome.py：这个文件里有哪些字段/数据结构？用中文回答" \
  -C /storage/emulated/0/Download/089 \
  --json \
  -o /storage/emulated/0/Download/089/_last_message.json \
  -s workspace-write \
  --skip-git-repo-check \
  --color never
```

提示词作为第一个位置参数直接写在命令里（wrapper 实际是 `''` + stdin 传入，效果一致）。

### 输出（真实抓包，10 行）

```json
{"type":"thread.started","thread_id":"01a0166a-9ba3-7c81-a678-c284c5887139"}
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"Model metadata for `deepseek-v4-flash` not found. Defaulting to fallback metadata; this can degrade performance and cause issues."}}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"我先看一下 `dome.py` 的内容。"}}
{"type":"item.started","item":{"id":"item_2","type":"command_execution","command":"/bin/sh -lc 'pwd && ls'","aggregated_output":"","exit_code":null,"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_2","type":"command_execution","command":"/bin/sh -lc 'pwd && ls'","aggregated_output":"/storage/emulated/0/Download/089\nAGENTS.md\nREADME.md\nconfig.toml\ndocs\ndome.py\npyproject.toml\nruns\nsrc\ntests\n","exit_code":0,"status":"completed"}}
{"type":"item.started","item":{"id":"item_3","type":"command_execution","command":"/bin/sh -lc 'wc -l dome.py && cat dome.py'","aggregated_output":"","exit_code":null,"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_3","type":"command_execution","command":"/bin/sh -lc 'wc -l dome.py && cat dome.py'","aggregated_output":"20 dome.py\nimport pygame\n...","exit_code":0,"status":"completed"}}
{"type":"item.completed","item":{"id":"item_4","type":"agent_message","text":"`dome.py`（共 20 行）是一个用 Pygame 绘制心形曲线的动画脚本，没有类定义，数据结构很少，主要如下：\n\n**字段/变量**\n- `screen`：..."}}
{"type":"turn.completed","usage":{"input_tokens":34953,"cached_input_tokens":33664,"cache_write_input_tokens":0,"output_tokens":577,"reasoning_output_tokens":47}}
```

### 字段结构

| 事件 `type` | 关键字段 |
| --- | --- |
| `thread.started` | `thread_id`（会话 ID，用于 resume） |
| `turn.started` | 无 |
| `item.started` / `item.updated` / `item.completed` | `item`：`{id, type, ...}`，按 `item.type` 不同字段不同 |
| `turn.completed` | `usage`：`{input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens, reasoning_output_tokens}` |
| `turn.failed` / `error` | 错误详情 |

`item.type` 取值及对应字段：

| `item.type` | 字段 |
| --- | --- |
| `agent_message` | `text`（回复全文，可含 `\n`） |
| `reasoning` | `text`（思考摘要，配置 `model_reasoning_summary=detailed` 才出现） |
| `command_execution` | `command`、`status`（`in_progress`/`completed`）、`aggregated_output`、`exit_code` |
| `file_change` / `web_search` / `mcp_tool_call` / `plan_update` | 各自的动作字段 |
| `error` | `message` |

兼容注意：旧版（<0.44）`item.type` 的字段名是 `item_type`，消息类型叫 `assistant_message`。

### 空内容结构

```jsonc
// command_execution 进行中：内容为空（aggregated_output 空串、exit_code null）
{"type":"item.started","item":{"id":"item_2","type":"command_execution",
  "command":"/bin/sh -lc 'pwd && ls'","aggregated_output":"","exit_code":null,"status":"in_progress"}}

// 本次没有 reasoning 条目：即使 turn.completed 里 reasoning_output_tokens=47，
// 未启用 detailed 摘要时流里就不会有 {"item":{"type":"reasoning",...}}

// -o 文件（_last_message.json）不是 JSONL，是最终回复的纯文本：
// `dome.py`（共 20 行）是一个用 Pygame 绘制心形曲线的动画脚本，没有类定义……
```

---

## 2. Claude（`claude -p '' --output-format stream-json`）

### 输入

wrapper 拼装的命令（`src/vulnhunt/cli/claude_code.py`）：

```bash
claude -p "分析 dome.py：这个文件里有哪些字段/数据结构？用中文回答" \
  --output-format stream-json \
  --include-partial-messages \
  --verbose \
  --permission-mode plan \
  --add-dir /storage/emulated/0/Download/089 \
  --session-id 22222222-2222-4222-8222-222222222222
```

提示词直接写在 `-p "..."` 里。

### 输出（真实抓包统计，2012 行）

| 顶层 `type` | 数量 |
| --- | --- |
| `system` | 601（`init` 1 / `status` 3 / `thinking_tokens` 597） |
| `stream_event` | 1402 |
| `assistant` | 6（`--include-partial-messages` 产生的部分消息） |
| `user` | 2 |
| `result` | 1 |

```jsonc
// system.init（会话初始化，一次）
{"type":"system","subtype":"init","cwd":"/storage/emulated/0/Download/089",
 "session_id":"22222222-...","tools":["Task","Bash","Read",...],
 "mcp_servers":[],"model":"deepseek-v4-flash[1m]","permissionMode":"plan",
 "slash_commands":[...],"claude_code_version":"2.1.234","output_style":"default",...}

// system.thinking_tokens（思考 token 计数，高频）
{"type":"system","subtype":"thinking_tokens","estimated_tokens":1,"estimated_tokens_delta":1,
 "uuid":"b1f775fb-...","session_id":"22222222-..."}

// stream_event 顶层固定 6 个字段
{"type":"stream_event","event":{...},"session_id":"22222222-...",
 "parent_tool_use_id":null,"uuid":"36e1923b-...","ttft_ms":339}

// event.type 六种：
{"type":"stream_event","event":{"type":"message_start","message":{"id":"b0eecb62-...",
  "type":"message","role":"assistant","model":"deepseek-v4-flash","content":[],
  "stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":23120,
  "cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0,"service_tier":"standard"}}},
 "session_id":"22222222-...","parent_tool_use_id":null,"uuid":"...","ttft_ms":339}

{"type":"stream_event","event":{"type":"content_block_start","index":0,
  "content_block":{"type":"thinking","thinking":"","signature":""}},"session_id":"...","uuid":"..."}

{"type":"stream_event","event":{"type":"content_block_delta","index":0,
  "delta":{"type":"thinking_delta","thinking":"The"}},"session_id":"...","uuid":"..."}
{"type":"stream_event","event":{"type":"content_block_delta","index":0,
  "delta":{"type":"signature_delta","signature":"b0eecb62-..."}},"session_id":"...","uuid":"..."}
{"type":"stream_event","event":{"type":"content_block_delta","index":1,
  "delta":{"type":"input_json_delta","partial_json":"{"}},"session_id":"...","uuid":"..."}
{"type":"stream_event","event":{"type":"content_block_delta","index":1,
  "delta":{"type":"text_delta","text":"`"}},"session_id":"...","uuid":"..."}

{"type":"stream_event","event":{"type":"content_block_stop","index":0},"session_id":"...","uuid":"..."}
{"type":"stream_event","event":{"type":"message_delta","delta":{"stop_reason":"end_turn",
  "stop_sequence":null},"usage":{...}},"session_id":"...","uuid":"..."}
{"type":"stream_event","event":{"type":"message_stop"},"session_id":"...","uuid":"..."}
```

### 字段结构

- 顶层 `type`：`system` / `assistant` / `user` / `stream_event` / `result`。
- `system.subtype`：`init`（会话信息）、`status`（请求状态）、`thinking_tokens`（思考计数）。
- `stream_event` 顶层：`type`、`event`、`session_id`、`parent_tool_use_id`、`uuid`、`ttft_ms`。
- `event.type` 六种：`message_start`、`content_block_start`、`content_block_delta`、`content_block_stop`、`message_delta`、`message_stop`。
- `content_block.type` 三种：`thinking`（`thinking`/`signature`）、`text`（`text`）、`tool_use`（`id`/`name`/`input`）。
- `delta.type` 四种：`thinking_delta`（`thinking`）、`signature_delta`（`signature`）、`input_json_delta`（`partial_json`）、`text_delta`（`text`）。
- `assistant` / `user`：`message.content` 数组，含部分内容（由 `--include-partial-messages` 产生）。
- `result`（最后一行，扁平字段）：`is_error`、`duration_api_ms`、`num_turns`、`stop_reason`、`session_id`、`total_cost_usd`、`usage`（含 `output_tokens_details`、`cache_creation` 等）。

本次真实统计：`content_block_delta` 共 1381（`thinking_delta` 597 / `text_delta` 698 / `input_json_delta` 83 / `signature_delta` 3），`content_block_start` 共 6（`thinking` 3 / `tool_use` 2 / `text` 1）。

### 空内容结构

```jsonc
// message_start：content 恒为空数组、stop_reason 为 null
"event":{"type":"message_start","message":{...,"content":[],"stop_reason":null,"stop_sequence":null,"usage":{...}}}

// content_block_start：三个类型的初始内容都是空
"event":{"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":"","signature":""}}
"event":{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"call_00_...","name":"Bash","input":{}}}
"event":{"type":"content_block_start","index":2,"content_block":{"type":"text","text":""}}

// thinking_delta / text_delta 逐 token 增量，单个事件内容可能只有 1 个字符
"event":{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"The"}}
"event":{"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"`"}}

// system.thinking_tokens 是流里最“空”的事件：只有两个计数
{"type":"system","subtype":"thinking_tokens","estimated_tokens":1,"estimated_tokens_delta":1,"uuid":"...","session_id":"..."}
```

---

## 3. wrapper 消费映射（联调）

| 用途 | Codex | Claude |
| --- | --- | --- |
| 会话续接 | `thread.started.thread_id` → `codex exec resume <id> -` | `--session-id <uuid>` 复用 |
| 流式显示思考 | `item.completed.item.type == "reasoning"` → `THINK` | `content_block_delta.delta.type == "thinking_delta"` → `THINK` |
| 流式显示回复 | `item.completed.item.type == "agent_message"` → `CODEX` | `content_block_delta.delta.type == "text_delta"` → `CLAUDE` |
| 完整 JSON 落盘 | 全部行 → `logs/codex_<task_id>.jsonl` | 全部行 → `logs/claude_round_<round>.jsonl` |
| 结构化结果 | `-o` 文件（纯文本 JSON）→ `tasks/<id>_result.json` | 末尾 `result` / `assistant` 文本 → `plans/round_<round>_plan.json` |
