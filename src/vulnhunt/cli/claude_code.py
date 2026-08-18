import json, uuid
from .base import run_process, resolve_executable
from ..models import Plan, TaskSpec
from ..prompts import planner_prompt
class ClaudeWrapper:
    def __init__(self,config): self.config=config; self.session_id=None
    def health_check(self): return self.config.dry_run or run_process([resolve_executable([self.config.claude_exec]),'--version'],timeout_s=20).exit_code==0
    def plan(self,goal,round_no,prior,work_dir):
        if self.config.dry_run: return Plan(round_no,goal,['代码入口','输入验证','数据流'],[TaskSpec('task_1','静态审计','审计目标代码中的高风险漏洞并给出证据',0),TaskSpec('task_2','边界分析','检查输入边界、路径和权限相关问题',1)])
        self.session_id=self.session_id or str(uuid.uuid4()); args=[resolve_executable([self.config.claude_exec]),'-p','', '--output-format','json','--permission-mode','plan','--add-dir',self.config.target_dir,'--session-id',self.session_id]
        r=run_process(args,cwd=work_dir,input_text=planner_prompt(goal,round_no,prior),timeout_s=self.config.claude_timeout_s)
        if r.exit_code: raise RuntimeError(r.stderr or 'claude failed')
        raw=json.loads(r.stdout).get('result',{}).get('text',r.stdout).strip().removeprefix('```json').removesuffix('```').strip(); return Plan.from_dict(json.loads(raw))
