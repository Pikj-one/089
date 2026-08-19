from pathlib import Path
from datetime import datetime, timezone
import json, os
from .models import Run

def now(): return datetime.now(timezone.utc).isoformat()
class RunStore:
    def __init__(self, run_dir):
        self.root=Path(run_dir); self.plans=self.root/'plans'; self.tasks=self.root/'tasks'; self.findings=self.root/'findings'; self.logs=self.root/'logs'; self.report=self.root/'report'
    @classmethod
    def create(cls, runs_root, run):
        started_at=datetime.now().strftime('%Y/%m/%d/%H-%M')
        s=cls(Path(runs_root)/started_at/run.run_id)
        for p in (s.root,s.plans,s.tasks,s.findings,s.logs,s.report): p.mkdir(parents=True,exist_ok=True)
        s.save_run(run); return s
    def _write(self,name,obj):
        p=self.root/name; p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_suffix(p.suffix+'.tmp'); tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8'); os.replace(tmp,p)
    def _read(self,name): return json.loads((self.root/name).read_text(encoding='utf-8'))
    def save_run(self,run): self._write('run.json',run.to_dict())
    def read_run(self): return Run.from_dict(self._read('run.json'))
    def save_state(self,state): self._write('state.json',state)
    def read_state(self): return self._read('state.json') if (self.root/'state.json').exists() else {}
    def save_plan(self,round_no,plan): self._write(f'plans/round_{round_no:03d}_plan.json',plan.to_dict())
    def read_plan(self,round_no): return self._read(f'plans/round_{round_no:03d}_plan.json')
    def save_task_result(self,task_id,result): self._write(f'tasks/{task_id}_result.json',result.to_dict())
    def read_task_result(self,task_id): return self._read(f'tasks/{task_id}_result.json')
    def save_task_input(self,task_id,data): self._write(f'tasks/{task_id}_input.json',data)
    def save_finding(self,finding_id,data): self._write(f'findings/{finding_id}.json',data)
    def append_log(self,name,line): (self.logs/name).open('a',encoding='utf-8').write(line+'\n')
