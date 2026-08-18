import json
from pathlib import Path
def build_report(run_dir):
    root=Path(run_dir); run=json.loads((root/'run.json').read_text(encoding='utf-8')); results=[json.loads(p.read_text(encoding='utf-8')) for p in (root/'tasks').glob('*_result.json')]; data={'run':run,'results':results}; (root/'report').mkdir(exist_ok=True); (root/'report'/'report.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); (root/'report'/'report.md').write_text('# VulnHunt Report\n\n'+run['goal']+'\n\n'+'\n'.join(f"- {x.get('task_id')}: {x.get('summary','')}" for x in results),encoding='utf-8'); return root/'report'/'report.md'
