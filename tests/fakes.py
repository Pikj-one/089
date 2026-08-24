from vulnhunt.config import Config
from vulnhunt.models import Plan, TaskSpec, WorkerResult


def config(**overrides):
    """构造完整 Config（字段无默认值，测试须提供全部字段；这里默认值仅是测试脚手架，非生产兜底）。"""
    base=dict(claude_exec="claude",codex_exec="codex",runs_root="runs",max_rounds=5,max_workers=3,
              claude_timeout_s=900,codex_timeout_s=100_000_000,codex_sandbox="danger-full-access",prettier_max_bytes=1_000_000)
    base.update(overrides)
    return Config(**base)


class FakeClaude:
    def plan(self, goal, round_no, prior, work_dir):
        return Plan(0, [TaskSpec("task_1", "静态审计", f"审计目标：{goal}")])


class FakeCodex:
    def exec_task(self, task, workspace):
        return WorkerResult(task.id, summary=f"completed: {task.title}")
