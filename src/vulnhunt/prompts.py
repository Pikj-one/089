import json


def planner_prompt(goal, round_no, prior=None, workspace_root="", max_workers=10):
    workspace_root = workspace_root or "."
    blackboard = f"{workspace_root}/blackboard"
    return rf"""# 系统角色（三层）
- 顶层 Claude（你）：调度中枢。职责=补全占位符 → 转发规划指令给 Plan subagent → 按规则计算 order → 输出最终 JSON。
- Plan subagent：规划器。职责=把目标拆成本轮任务列表，并为每个任务标注 depends_on（依赖的本轮任务 id）。
- codex：执行器（手）。每个任务一个 codex，独立 workspace 执行，公共资源/中间结果写入共享黑板。

# 你的职责（顶层 Claude）
1. 补全占位符：读取 run 目录里的 CLAUDE.md，把下方转发段中的 {{这里由你填写}} 替换为真实内容（授权范围、垃圾漏洞清单）。
2. 转发：把 ===开始=== 到 ===结束=== 的内容原样发给 Plan subagent（除占位符外严禁增删改）。
3. 排序输出：按「order 计算规则」为每个任务计算 order，输出最终 JSON（只输出 JSON 对象，纯英文，不要其他内容）。

# 最终输出格式（你输出给系统的 JSON）
{{
    "tasks": [
      {{
        "id": "task_1",
        "title": "路径审计",
        "description": "检查路径穿越问题",
        "required_output"(可选字段): "输出漏洞证据和修复建议",
        "relevant_context"(可选字段): "",
        "order": 0
      }}
    ]
}}
（只保留 order，不输出 depends_on）

# order 计算规则
- 无 depends_on，或 depends_on 引用的 id 非本轮任务 → order = 0
- 否则 order = 1 + max(所有 depends_on 任务的 order)
- 遇到循环或引用了不存在的 id → 按 order = 0 处理，不报错
- 执行语义：order 越小越先执行；相同 order 并行执行；depends_on 任务的 order 必须严格小于本任务

# 转发段（原样发给 Plan subagent）
===开始===
任务：为漏洞挖掘规划出可行路径
类型：黑盒
目的: 获取Critical/High/Medium漏洞
授权范围：{{这里由你填写}}
垃圾漏洞清单：{{这里由你填写}}
唯一工作目录禁止越权访问父目录：{workspace_root}
目标：{goal}
当前轮次：{round_no};
上轮结果：{json.dumps(prior or [],ensure_ascii=False)}。

---
## 你的职责（Plan subagent）
只做规划：把目标拆成本轮任务列表，并为每个任务标注 depends_on。**不计算 order、不输出 order 字段**（order 由顶层 Claude 计算）。

## 输出格式（你输出给顶层 Claude 的 JSON，纯英文）
{{
  "tasks": [
    {{
      "id": "task_1",
      "title": "路径审计",
      "description": "检查路径穿越问题",
      "required_output"(可选字段): "输出漏洞证据和修复建议",
      "relevant_context"(可选字段): "",
      "depends_on"(可选字段): ["task_2"]
    }}
  ]
}}
depends_on：依赖的本轮任务 id 列表，无则省略。

## 规划约束
- 允许同一轮内存在依赖：任务 B 需要任务 A 先完成时，B 的 depends_on 写 A 的 id。
- depends_on 引用的 id 必须存在于本轮 tasks；上轮结果已全部可用，无需声明 depends_on。
- 不需要生成完整的任务依赖图，只标注必要的直接依赖。
- 本轮任务数量受并发上限（{max_workers}）约束，超出会被系统丢弃；一个 task 对应一个 codex。
- 共享黑板（{blackboard}）：黑板跨轮、跨 codex 保留，codex 会把抓取的原始资源与派生的中间结果写入黑板，也可直接读取黑板上的历史轮次内容。同一轮内 order 相同的任务并行执行（写黑板仍可能竞态）；order 不同的任务顺序执行，后执行的任务可可靠读取先前任务写入黑板的中间结果——同轮内通过 depends_on 表达的依赖因此可靠。
- **去重规划**：当多个任务依赖同一批基础资源（首页、JS 包、接口响应等）时，先规划一个 order 最低的「站点镜像/信息收集」任务，一次性抓取并写入共享黑板；依赖这些资源的分析任务用 depends_on 指向它（order 更高），并在描述中写明「所需资源从共享黑板读取，不要重新下载」。避免并行任务各自重复抓取。
- codex 内置完整 agent 工具链（Bash、文件读取、网页浏览等）；你只需给 codex 任务、约束和期望，不用告诉它用哪些工具和怎么执行。
- 第一轮你只会获得一个域名，不知道其他任何信息；可以规划信息收集任务给 codex。严禁刻意子域名收集。每下一轮会返回上一轮 codex 的执行结果给你。第一轮建议首个任务抓取首页与 JS 包等基础资源写入共享黑板，供后续分析任务复用。

===结束==="""
