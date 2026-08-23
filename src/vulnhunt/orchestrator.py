from .models import RunStatus
from .workers import WorkerPool
from .state import now
import threading
class Orchestrator:
    def __init__(self,config,store,claude,codex):
        self.config=config; self.store=store; self.claude=claude; self.codex=codex; self.run=store.read_run(); self.prior=[]; self.plan=None; self._abort=threading.Event(); self.claude.cancel_event=self._abort; self.codex.cancel_event=self._abort
        if self.run.current_round:
            try:
                from .models import Plan
                self.plan=Plan.from_dict(store.read_plan(self.run.current_round))
            except (FileNotFoundError, KeyError, ValueError):
                pass
    def run_loop(self):
        try:
            while self.run.status not in (RunStatus.COMPLETE,RunStatus.FAILED,RunStatus.ABORTED): self.step()
        except KeyboardInterrupt: self.run.status=RunStatus.ABORTED; self.save()
        except Exception as e:
            self.run.status=RunStatus.ABORTED if self._abort.is_set() else RunStatus.FAILED
            if self.store:
                self.store.append_log(f'round_{self.run.current_round:03d}.log', f'run failed: {type(e).__name__}: {e}')
            self.save()
        return self.run
    def request_abort(self): self._abort.set()
    def save(self): self.run.updated_at=now(); self.store.save_run(self.run)
    def step(self):
        if self._abort.is_set(): self.run.status=RunStatus.ABORTED; self.save(); return
        if self.run.status==RunStatus.INIT: self.run.current_round=1; self.run.status=RunStatus.PLANNING
        elif self.run.status==RunStatus.PLANNING:
            self.plan=self.claude.plan(self.run.goal,self.run.current_round,self.prior,self.store.root.resolve()); self.plan.round=self.run.current_round; self.store.save_plan(self.run.current_round,self.plan); self.run.status=RunStatus.DISPATCHING
        elif self.run.status==RunStatus.DISPATCHING: self.run.status=RunStatus.RUNNING
        elif self.run.status==RunStatus.RUNNING:
            self.prior=[r.to_dict() for r in WorkerPool(self.config,self.codex,self.store).run(self.plan.tasks,self.run.current_round)]; self.run.status=RunStatus.COLLECTING
        elif self.run.status==RunStatus.COLLECTING: self.run.status=RunStatus.DECISION
        elif self.run.status==RunStatus.DECISION:
            if self.run.current_round>=self.config.max_rounds: self.run.status=RunStatus.COMPLETE
            else: self.run.current_round+=1; self.run.status=RunStatus.PLANNING
        self.save(); self.store.save_state({'status':self.run.status.value,'round':self.run.current_round})
