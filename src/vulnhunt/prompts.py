import json


def planner_prompt(goal, round_no, prior=None):
    return rf"""
你可以启动不等个codex作为Explore Agent来执行一切(注:Explore Agent受Plan模式影响而codex不会,Explore Agent能做的codex也能做,所以启动codex而不是Explore Agent.codex最大同时启动十个)。
任务：为漏洞挖掘规划出可行路径
目的：获取Critical/High漏洞
codex介绍：codex内置完整工具链如bash使用、文件读取、网页浏览等

---

## 输入内容
目标：{goal}是需要漏洞挖掘的域名
当前轮次：{round_no}；
上轮结果：{json.dumps(prior or [],ensure_ascii=False)}。

## 输出期望
### 输出约定
每个codex都是相互独立的,不要让他们直接依赖其他codex的成果来执行,必须通过你中转
你的最终产物应该是一份位于`C:\Users\Cutey\.claude\plans`的完整计划里面不存JSON数组,一段调用ExitPlanMode后产出的tasks JSON数组
### 输出格式
你只能输出JSON数组,系统会把每个task转发给codex,所以你只能必须百分百是如下输出格式:
{{
    "tasks": [
      {{
        "id": "task_1",
        "title": "路径审计",
        "description": "检查路径穿越问题",
        "priority"(可选字段): 1,
        "required_output"(可选字段): "输出漏洞证据和修复建议",
        "relevant_context"(可选字段): ""
      }},
      {{
        "id": "task_2",
        "title": "xxx",
        "description": "xxx",
        "priority"(可选字段): x,
        "required_output"(可选字段): "xxx",
        "relevant_context"(可选字段): ""
      }}
    ]
  }}

"""
