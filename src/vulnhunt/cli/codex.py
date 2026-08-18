import json
from pathlib import Path
from .base import run_process, resolve_executable
from ..models import WorkerResult, TaskResultStatus
class CodexWrapper:
    def __init__(self,config): self.config=config
    def health_check(self): return self.config.dry_run or run_process([resolve_executable([self.config.codex_exec]),'--version'],timeout_s=20).exit_code==0
    def exec_task(self,task,workspace):
        if self.config.dry_run: return WorkerResult(task.id,summary=f'dry-run completed: {task.title}')
        args=[resolve_executable([self.config.codex_exec]),'exec','', '-C',str(workspace),'--json','-o',str(Path(workspace)/'_last_message.json'),'-s',self.config.codex_sandbox,'--skip-git-repo-check','--ephemeral','--color','never']; r=run_process(args,cwd=workspace,input_text=task.description,timeout_s=self.config.codex_timeout_s); p=Path(workspace)/'_last_message.json'
        if p.exists(): d=json.loads(p.read_text(encoding='utf-8')); d['task_id']=task.id; return WorkerResult.from_dict(d)
        return WorkerResult(task.id,r.exit_code,TaskResultStatus.FAILURE,error=r.stderr,stdout_tail=r.stdout[-4000:],stderr_tail=r.stderr[-4000:],duration_s=r.duration_s)
