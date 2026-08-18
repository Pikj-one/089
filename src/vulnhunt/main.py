import argparse, uuid
from datetime import datetime, timezone
from .config import load_config
from .models import Run
from .state import RunStore
from .cli.claude_code import ClaudeWrapper
from .cli.codex import CodexWrapper
from .orchestrator import Orchestrator
from .report import build_report
def main(argv=None):
    p=argparse.ArgumentParser(prog='vulnhunt'); sub=p.add_subparsers(dest='cmd',required=True); s=sub.add_parser('start'); s.add_argument('goal'); s.add_argument('--config',default='config.toml'); sub.add_parser('doctor'); r=sub.add_parser('resume'); r.add_argument('run_dir')
    a=p.parse_args(argv); c=load_config(getattr(a,'config','config.toml')); claude=ClaudeWrapper(c); codex=CodexWrapper(c)
    if a.cmd=='doctor': print('claude:',claude.health_check()); print('codex:',codex.health_check()); return
    if a.cmd=='resume': store=RunStore(a.run_dir)
    else:
        run=Run(uuid.uuid4().hex[:12],a.goal,datetime.now(timezone.utc).isoformat(),max_rounds=c.max_rounds,config_snapshot=c.__dict__,target_dir=c.target_dir); store=RunStore.create(c.runs_root,run)
    result=Orchestrator(c,store,claude,codex).run_loop(); print(result.status.value); print(build_report(store.root))
