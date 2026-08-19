import json


def planner_prompt(goal, round_no, prior=None):
    return rf"""
你要启动Plan subagent为赏金任务规划出高价值赏金路径而不是自己去规划，你只负责聚合，Plan subagent负责规划，codex负责执行(注：不要让codex给出方向建议，只当他是无脑执行器)
任务：为黑盒漏洞挖掘规划出可行路径
目的：获取Critical/High漏洞
启动N个codex来执行一切而不是自己使用bash命令，启动见##输出期望

---

## 输入预期
你只会获得一个具体的域名，不用子域名收集因为这是个可测试的域名
目标：{goal}
当前轮次：{round_no}；
上轮结果：{json.dumps(prior or [],ensure_ascii=False)}。

## 输出期望
codex介绍：codex内置完整agent工具链如bash使用、文件读取、网页浏览等。一轮最多并行十个codex一个task对应一个codex，超出十个的task会被系统默认丢弃不会排队
在终端显示输出JSON对象，JSON对象会被系统解析发送给codex 不要其他内容只要json对象
{{
    "tasks": [
      {{
        "id": "task_1",
        "title": "路径审计",
        "description": "检查路径穿越问题",
        "required_output"(可选字段): "输出漏洞证据和修复建议",
        "relevant_context"(可选字段): ""
      }},
      {{
        "id": "task_2",
        "title": "xxx",
        "description": "xxx",
        "required_output"(可选字段): "xxx",
        "relevant_context"(可选字段): ""
      }}
    ]
}}
"""
