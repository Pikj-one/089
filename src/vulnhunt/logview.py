"""Rendering and replay helpers for Claude stream-json logs."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Iterable

TOOL_RESULT_TRUNC = 2000
TOOL_RESULT_LINES = 30
TOOL_INPUT_TRUNC = 500
THINK_TRUNC = 2000
TEXT_TRUNC = 4000
RESULT_TRUNC = 500


def truncate(text, limit, lines=0):
    text = str(text or "")
    if lines:
        parts = text.splitlines()
        if len(parts) > lines:
            text = "\n".join(parts[:lines]) + f" … [{len(parts) - lines} lines truncated]"
    if len(text) > limit:
        text = text[:limit] + " … [truncated]"
    return text


def format_line(component, message):
    from time import strftime
    return f"[{strftime('%H:%M:%S')}][{component}] {message}"


@dataclass
class LogAction:
    component: str
    message: str


@dataclass
class StreamAction:
    component: str
    text: str


@dataclass
class StreamEndAction:
    pass


def is_plan_stream(ev, event, plan_tool_ids):
    return (ev.get("subagent_type") == "Plan" or event.get("subagent_type") == "Plan"
            or ev.get("parent_tool_use_id") in plan_tool_ids
            or event.get("parent_tool_use_id") in plan_tool_ids)


def _content_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in value)
    return json.dumps(value, ensure_ascii=False, default=str)


class ClaudeLogRenderer:
    def __init__(self):
        self._progress_logged = {}
        self._top_streamed = False
        self._blocks = {}

    def feed(self, ev, plan_stream=False):
        if not isinstance(ev, dict):
            return []
        event = ev.get("event") if isinstance(ev.get("event"), dict) else ev
        etype = event.get("type")
        actions = []
        if etype == "system":
            subtype = event.get("subtype")
            if subtype == "init":
                actions.append(LogAction("CLAUDE-PLAN", f"session: model={event.get('model','')} v={event.get('claude_code_version','')} {event.get('permissionMode','')} tools={len(event.get('tools') or [])}"))
            elif subtype == "status":
                actions.append(LogAction("CLAUDE-PLAN", f"status: {event.get('status') or event.get('message') or ''}"))
            elif subtype == "task_started":
                kind = "子代理" if event.get("task_type") == "local_agent" else "后台任务"
                desc = event.get("description") or ""
                actions.append(LogAction("CLAUDE-PLAN", f"{kind}启动：{desc}"))
                if event.get("task_id"):
                    self._progress_logged[event["task_id"]] = desc
            elif subtype == "task_progress":
                task_id, desc = event.get("task_id") or "", event.get("description") or ""
                if desc and self._progress_logged.get(task_id) != desc:
                    self._progress_logged[task_id] = desc
                    actions.append(LogAction("CLAUDE-PLAN", f"正在执行：{desc}"))
            elif subtype == "task_notification":
                kind = "子代理" if event.get("task_type") == "local_agent" else "后台任务"
                actions.append(LogAction("CLAUDE-PLAN", f"{kind}结束（{event.get('status') or '?'}）：{event.get('summary') or ''}"))
            elif subtype == "background_tasks_changed":
                for task in event.get("tasks") or []:
                    tid, desc = task.get("task_id") or "", task.get("description") or ""
                    if desc and self._progress_logged.get(tid) != desc:
                        self._progress_logged[tid] = desc
                        actions.append(LogAction("CLAUDE-PLAN", f"后台任务：{desc}"))
            elif subtype not in ("thinking_tokens",):
                actions.append(LogAction("CLAUDE", f"{subtype or 'system'}: {truncate(json.dumps(event, ensure_ascii=False), TEXT_TRUNC)}"))
            return actions
        if etype == "stream_event":
            return actions
        if etype == "message_start":
            msg = event.get("message") or {}
            actions.append(LogAction("CLAUDE", f"turn: model={msg.get('model','')} in={msg.get('usage',{}).get('input_tokens','')} ttft={event.get('ttft_ms','')}ms"))
            self._top_streamed = True
        elif etype == "content_block_start":
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use":
                initial_input = block.get("input")
                self._blocks[event.get("index", 0)] = {"kind": "tool_use", "name": block.get("name", ""), "tool_id": block.get("id", ""), "input_json": json.dumps(initial_input, ensure_ascii=False) if initial_input else ""}
        elif etype == "content_block_delta":
            delta = event.get("delta") or {}
            dtype = delta.get("type")
            component = "CLAUDE-PLAN" if plan_stream else ("CLAUDE-THINK" if dtype == "thinking_delta" else "CLAUDE")
            if dtype == "thinking_delta" and delta.get("thinking"):
                actions.append(StreamAction(component, truncate(delta["thinking"], THINK_TRUNC)))
            elif dtype == "text_delta" and delta.get("text"):
                actions.append(StreamAction(component, truncate(delta["text"], TEXT_TRUNC)))
            elif dtype == "input_json_delta":
                index = event.get("index", 0)
                block = self._blocks.setdefault(index, {"kind": "tool_use", "name": "", "tool_id": "", "input_json": ""})
                block["input_json"] += delta.get("partial_json", "")
        elif etype == "content_block_stop":
            index = event.get("index", 0)
            block = self._blocks.pop(index, None)
            if block and block.get("kind") == "tool_use":
                raw = block.get("input_json", "")
                try:
                    raw = json.dumps(json.loads(raw), ensure_ascii=False)
                except json.JSONDecodeError:
                    raw = truncate(raw, TOOL_INPUT_TRUNC)
                actions.append(LogAction("CLAUDE-TOOL", f"tool: {block.get('name','')} {raw}"))
            else:
                actions.append(StreamEndAction())
        elif etype == "message_delta":
            usage = event.get("usage") or {}
            actions.append(LogAction("CLAUDE", f"turn end: stop={event.get('delta',{}).get('stop_reason','')} in={usage.get('input_tokens','')} out={usage.get('output_tokens','')}"))
        elif etype == "message_stop":
            actions.append(StreamEndAction())
        elif etype == "assistant":
            is_plan = bool(ev.get("subagent_type"))
            if not is_plan and self._top_streamed:
                return actions
            for block in (ev.get("message") or {}).get("content") or []:
                kind = block.get("type")
                component = "CLAUDE-PLAN" if is_plan else "CLAUDE"
                if kind == "thinking": actions.append(LogAction(component, f"思考：{truncate(block.get('thinking',''), THINK_TRUNC)}"))
                elif kind == "text": actions.append(LogAction(component, truncate(block.get("text", ""), TEXT_TRUNC)))
                elif kind == "tool_use": actions.append(LogAction(component, f"tool: {block.get('name','')} {truncate(json.dumps(block.get('input',{}), ensure_ascii=False), TOOL_INPUT_TRUNC)}"))
        elif etype == "user":
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_result":
                    content = block.get("content", ev.get("tool_use_result", ""))
                    error = " [ERROR]" if block.get("is_error") else ""
                    component = "CLAUDE-PLAN" if plan_stream else "CLAUDE-TOOL"
                    actions.append(LogAction(component, f"result {str(block.get('tool_use_id',''))[:12]}{error}: {truncate(_content_text(content), TOOL_RESULT_TRUNC, TOOL_RESULT_LINES)}"))
                elif block.get("type") == "text":
                    actions.append(LogAction("CLAUDE", f"[user text] {truncate(block.get('text',''), TEXT_TRUNC)}"))
        elif etype == "result":
            actions.extend([LogAction("ORCH", f"round done: {ev.get('subtype','')} is_error={ev.get('is_error',False)} turns={ev.get('num_turns','')} dur={ev.get('duration_ms','')} cost=${ev.get('total_cost_usd','')}"), LogAction("CLAUDE", f"final({ev.get('stop_reason','')}): {truncate(_content_text(ev.get('result','')), RESULT_TRUNC)}"), LogAction("CLAUDE", f"usage: in={(ev.get('usage') or {}).get('input_tokens','')} out={(ev.get('usage') or {}).get('output_tokens','')} thinking={(ev.get('usage') or {}).get('thinking_tokens','')} cache_w={(ev.get('usage') or {}).get('cache_creation_input_tokens','')} cache_r={(ev.get('usage') or {}).get('cache_read_input_tokens','')}")])
        elif etype:
            actions.append(LogAction("CLAUDE", f"{etype}: {truncate(json.dumps(ev, ensure_ascii=False), TEXT_TRUNC)}"))
        return actions


class AggregateSink:
    def __init__(self, emit: Callable[[str, str], None]):
        self.emit = emit
        self.component = None
        self.parts = []

    def _flush(self):
        if self.component is not None:
            self.emit(self.component, "".join(self.parts))
            self.component, self.parts = None, []

    def log(self, component, message):
        self._flush(); self.emit(component, message)

    def stream(self, component, text):
        if self.component != component:
            self._flush(); self.component = component
        self.parts.append(text)

    def stream_end(self):
        self._flush()


def replay_file(path: str | Path, sink: AggregateSink, plan_tool_ids: Iterable[str] = ()):
    renderer = ClaudeLogRenderer()
    ids = set(plan_tool_ids)
    with Path(path).open(encoding="utf-8") as source:
        for line in source:
            try: ev = json.loads(line)
            except json.JSONDecodeError: continue
            event = ev.get("event") if isinstance(ev.get("event"), dict) else ev
            plan = is_plan_stream(ev, event, ids)
            for action in renderer.feed(ev, plan):
                if isinstance(action, LogAction): sink.log(action.component, action.message)
                elif isinstance(action, StreamAction): sink.stream(action.component, action.text)
                else: sink.stream_end()
    sink.stream_end()
