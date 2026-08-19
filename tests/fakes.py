from vulnhunt.models import Plan, TaskSpec, WorkerResult


class FakeClaude:
    def plan(self, goal, round_no, prior, work_dir):
        return Plan(0, [TaskSpec("task_1", "静态审计", f"审计目标：{goal}")])


class FakeCodex:
    def exec_task(self, task, workspace):
        return WorkerResult(task.id, summary=f"completed: {task.title}")
