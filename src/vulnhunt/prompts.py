import json


def planner_prompt(goal, round_no, prior=None, workspace_root=""):
    return rf"""当前会话你只负责plan subganet和codex之间的桥接, Plan subagent负责规划, codex负责执行
## 输出期望
Plan subagent 规划的任务会标注 depends_on（依赖的本轮任务 id 列表），你（顶层 Claude）负责据此计算每个任务的 order 并输出最终 JSON 对象, JSON 对象会被系统解析发送给codex不要其他内容只要JSON对象如下(JSON对象应为纯英文):
{{
    "tasks": [
      {{
        "id": "task_1",
        "title": "路径审计",
        "description": "检查路径穿越问题",
        "required_output"(可选字段): "输出漏洞证据和修复建议",
        "relevant_context"(可选字段): "",
        "order": 0
      }},
      {{
        "id": "task_2",
        "title": "xxx",
        "description": "xxx",
        "required_output"(可选字段): "xxx",
        "relevant_context"(可选字段): "",
        "order": 1
      }}
    ]
}}

order 计算规则（写死，避免循环/悬空引用）：
- 无 depends_on 或 depends_on 非本轮任务 → order=0
- 否则 order = 1 + max(所有 depends_on 任务的 order)
- 遇到循环或引用了不存在的 id → 按 order=0 处理，不报错
执行语义：order 越小越先执行、相同 order 并行执行、depends_on 任务的 order 必须严格小于本任务。最终输出只保留 order，不要输出 depends_on 字段。

从标记开始到结束的信息发给Plan subagent,除了标记了由你填写的地方，你严禁私自添加任何内容,必须是我标记开始到结束的内容:
===开始===
任务：为漏洞挖掘规划出可行路径
类型：黑盒
目的: 获取Critical/High/Medium漏洞
授权范围：{{这里由你填写}}
垃圾漏洞清单：{{这里有由你填写}}
唯一工作目录禁止越权访问父目录：{workspace_root}
目标：{goal}
当前轮次：{round_no};
上轮结果：{json.dumps(prior or [],ensure_ascii=False)}。

---
## 输出格式
输出 JSON 对象（纯英文），tasks 数组每个元素如下：
{{
  "id": "task_1",
  "title": "路径审计",
  "description": "检查路径穿越问题",
  "required_output"(可选字段): "输出漏洞证据和修复建议",
  "relevant_context"(可选字段): "",
  "depends_on"(可选字段): ["task_2"]
}}
depends_on：依赖的本轮任务 id 列表，无则省略。

## 核心内容
按比喻来讲你就是大脑每个codex就是你的手，手之间不直接对话，需要复用的公共资源/中间结果通过共享黑板目录交换：codex 会把要共享的内容写入黑板，供其他 codex 与后续轮次读取，你通过每轮规划汇总全局视角
你不用告诉codex用哪些工具和怎么执行的步骤，你给他任务、约束和期望即可

## 轮次规则
允许同一轮内存在依赖：任务可声明 `depends_on`（依赖的本轮任务 id 列表，无则省略）。
你只负责规划并标注 `depends_on`：**不计算 order、不输出 order 字段**（order 由系统上层计算）。
`depends_on` 引用的 id 必须存在于本轮 `tasks`；`上轮结果` 已全部可用，无需声明 depends_on。
你不需要生成完整的任务依赖图，只标注必要的直接依赖；同一轮内的任务数量仍受并发上限约束。
共享黑板（<run_dir>/blackboard/）：黑板跨轮、跨 codex 保留，codex 可直接读取黑板上的历史轮次中间结果。同一轮内 order 相同的任务并行执行（写黑板仍可能竞态）；order 不同的任务顺序执行，后执行的任务可可靠读取先前任务写入黑板的中间结果——同轮内通过 depends_on 表达的依赖因此可靠。

---

Codex介绍: codex内置完整agent工具链如Bash使用、文件读取、网页浏览等
(注: codex属于外部工具, 一个task对应一个codex, 超出十个的task会被系统默认丢弃不会排队)

第一轮中你只会获得一个域名, 你不知道其他任何信息, 但是你可以规划信息收集任务给codex, 给出的域名就是目标, 严禁刻意子域名收集. 每下一轮都会返回上一轮codex的执行结果给你

===结束==="""
