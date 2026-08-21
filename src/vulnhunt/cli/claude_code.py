import json, uuid
from pathlib import Path
from .base import run_process, resolve_executable
from ..models import Plan, TaskSpec
from ..prompts import planner_prompt
from ..logview import ClaudeLogRenderer, LogAction, StreamAction, StreamEndAction, is_plan_stream
class ClaudeWrapper:
    def __init__(self,config,logger=None,store=None,streamer=None,stream_end=None):
        self.config=config; self.session_id=None; self.logger=logger or (lambda component,message: None); self.cancel_event=None; self.store=store; self.streamer=streamer; self.stream_end=stream_end or (lambda: None); self._renderer=ClaudeLogRenderer()
    def health_check(self): return run_process([resolve_executable([self.config.claude_exec]),'--version'],timeout_s=20).exit_code==0
    def plan(self,goal,round_no,prior,work_dir):
        work_dir=Path(work_dir).resolve()
        target_dir=Path(self.config.target_dir).resolve()
        self.session_id=self.session_id or str(uuid.uuid4()); args=[resolve_executable([self.config.claude_exec]),'-p','', '--output-format','stream-json','--include-partial-messages','--verbose','--permission-mode','bypassPermissions','--add-dir',str(target_dir),'--session-id',self.session_id]
        subagent_input_parts={}
        tool_ids_by_index={}
        plan_tool_ids=set()
        plan_subagent_logged=False

        def apply(action):
            if isinstance(action, LogAction): self.logger(action.component, action.message)
            elif isinstance(action, StreamAction): self.streamer(action.component, action.text) if self.streamer else self.logger(action.component, action.text)
            elif isinstance(action, StreamEndAction): self.stream_end()

        def capture_plan_subagent(value):
            nonlocal plan_subagent_logged
            if not isinstance(value, dict):
                return False
            if value.get('subagent_type') == 'Plan':
                if not plan_subagent_logged:
                    self.stream_end()
                    self.logger('CLAUDE-PLAN', 'subagent_type=Plan')
                    plan_subagent_logged=True
                return True
            found=False
            for child in value.values():
                if isinstance(child, dict):
                    found=capture_plan_subagent(child) or found
                elif isinstance(child, list):
                    for item in child:
                        found=capture_plan_subagent(item) or found
            return found

        def remember_plan_tool(value, index=None):
            if not isinstance(value, dict):
                return
            if value.get('type') == 'tool_use':
                tool_id=value.get('id')
                if tool_id and capture_plan_subagent(value.get('input', {})):
                    plan_tool_ids.add(tool_id)
                    if index is not None:
                        tool_ids_by_index[index]=tool_id
            for child in value.values():
                if isinstance(child, dict):
                    remember_plan_tool(child, index)
                elif isinstance(child, list):
                    for item in child:
                        remember_plan_tool(item, index)

        def on_line(line):
            if self.store: self.store.append_log(f'claude_round_{round_no:03d}.jsonl', line)
            try: ev=json.loads(line)
            except json.JSONDecodeError: return
            event=ev.get('event') if isinstance(ev.get('event'), dict) else ev
            event_index=event.get('index')
            remember_plan_tool(event.get('content_block', {}), event_index)
            remember_plan_tool(ev.get('message', {}))
            capture_plan_subagent(ev)
            etype=event.get('type')
            if etype == 'content_block_delta':
                delta=event.get('delta') or {}
                if delta.get('type') == 'input_json_delta':
                    index=event.get('index')
                    partial=delta.get('partial_json', '')
                    if index is not None and partial:
                        subagent_input_parts[index]=subagent_input_parts.get(index, '') + partial
                        try:
                            input_data=json.loads(subagent_input_parts[index])
                            if capture_plan_subagent(input_data):
                                tool_id=tool_ids_by_index.get(index)
                                if tool_id:
                                    plan_tool_ids.add(tool_id)
                        except json.JSONDecodeError:
                            pass
            plan_stream=is_plan_stream(ev, event, plan_tool_ids)
            for action in self._renderer.feed(ev, plan_stream): apply(action)
        r=run_process(args,cwd=work_dir,input_text=planner_prompt(goal,round_no,prior,work_dir),timeout_s=self.config.claude_timeout_s,cancel_event=self.cancel_event,on_stdout_line=on_line)
        if r.exit_code: raise RuntimeError(r.stderr or 'claude failed')
        envelopes=[]
        for line in r.stdout.splitlines():
            try: envelopes.append(json.loads(line))
            except json.JSONDecodeError: pass
        envelope=next((item for item in reversed(envelopes) if item.get('type') == 'result'), envelopes[-1] if envelopes else {})
        result=envelope.get('result', r.stdout)
        raw=result.get('text', '') if isinstance(result, dict) else result
        raw=(raw or r.stdout).strip().removeprefix('```json').removesuffix('```').strip()
        if raw.startswith('{') and '\n{' in raw: raw=raw.splitlines()[-1]
        plan=Plan.from_dict(json.loads(raw)); self.logger("CLAUDE", f"第 {round_no} 轮规划完成：拆分 {len(plan.tasks)} 个任务"); return plan
