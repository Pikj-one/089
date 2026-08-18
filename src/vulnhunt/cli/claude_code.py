import json, uuid
from .base import run_process, resolve_executable
from ..models import Plan, TaskSpec
from ..prompts import planner_prompt
class ClaudeWrapper:
    def __init__(self,config,logger=None): self.config=config; self.session_id=None; self.logger=logger or (lambda component,message: None); self.cancel_event=None
    def health_check(self): return self.config.dry_run or run_process([resolve_executable([self.config.claude_exec]),'--version'],timeout_s=20).exit_code==0
    def plan(self,goal,round_no,prior,work_dir):
        if self.config.dry_run:
            plan=Plan(round_no,goal,['代码入口','输入验证','数据流'],[TaskSpec('task_1','静态审计','审计目标代码中的高风险漏洞并给出证据',0),TaskSpec('task_2','边界分析','检查输入边界、路径和权限相关问题',1)])
            self.logger("CLAUDE", f"第 {round_no} 轮规划完成：拆分 {len(plan.tasks)} 个任务，攻击面包括 {', '.join(plan.attack_surface)}")
            return plan
        self.session_id=self.session_id or str(uuid.uuid4()); args=[resolve_executable([self.config.claude_exec]),'-p','', '--output-format','json','--permission-mode','plan','--add-dir',self.config.target_dir,'--session-id',self.session_id]
        r=run_process(args,cwd=work_dir,input_text=planner_prompt(goal,round_no,prior),timeout_s=self.config.claude_timeout_s,cancel_event=self.cancel_event,on_stdout_line=lambda line: self.logger("CLAUDE", line))
        if r.exit_code: raise RuntimeError(r.stderr or 'claude failed')
        envelope=json.loads(r.stdout)
        result=envelope.get('result', r.stdout)
        raw=result.get('text', '') if isinstance(result, dict) else result
        raw=(raw or r.stdout).strip().removeprefix('```json').removesuffix('```').strip()
        plan=Plan.from_dict(json.loads(raw)); self.logger("CLAUDE", "完整 Plan 结果：\n" + json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)); return plan
