import json


def planner_prompt(goal, round_no, prior=None):
    return rf"""
You need to launch the Plan subagent to plan high-value bounty paths for bounty tasks instead of planning them yourself. You are only responsible for aggregation, the Plan subagent is responsible for planning, and Codex is responsible for execution (Note: do not let Codex provide directional suggestions; treat it only as a mindless executor).
Task: Plan feasible paths for black-box vulnerability discovery.
Objective: Obtain Critical/High vulnerabilities.
Launch N Codex instances to execute everything instead of using bash commands yourself. Refer to the ## Expected Output section for launch details.

---

## Expected Input
You will only receive a specific domain name. No subdomain collection is needed because this is an already testable domain.
Goal: {goal}
Current round: {round_no};
Previous round results: {json.dumps(prior or [], ensure_ascii=False)}.

## Expected Output
Codex Introduction: Codex has a complete built-in agent toolchain, including bash usage, file reading, web browsing, etc. A maximum of ten Codex instances can run in parallel per round; each task corresponds to one Codex instance. Tasks exceeding ten will be automatically discarded by the system and will not be queued.
Display the output as a JSON object in the terminal. The JSON object will be parsed by the system and sent to Codex. Do not include any other content—only the JSON object.
{{
    "tasks": [
      {{
        "id": "task_1",
        "title": "Path Traversal Audit",
        "description": "Check for path traversal issues",
        "required_output"(optional field): "Output vulnerability evidence and remediation suggestions",
        "relevant_context"(optional field): ""
      }},
      {{
        "id": "task_2",
        "title": "xxx",
        "description": "xxx",
        "required_output"(optional field): "xxx",
        "relevant_context"(optional field): ""
      }}
    ]
}}

"""
