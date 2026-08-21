import json


def planner_prompt(goal, round_no, prior=None, workspace_root=""):
    return rf"""
当前会话你只负责中转, Plan subagent负责规划, codex负责执行
只能读取、写入和创建该目录及其子目录中的文件。禁止读取、搜索、列出或使用该目录的任何父目录、兄弟目录或其他本地路径。不要通过 ..、绝对路径、工作目录切换或 shell 命令访问工作目录之外的内容。
## 输出期望
拆分plam sunagent规划的任务在终端显示输出JSON对象, JSON对象会被系统解析发送给codex不要其他内容只要JSON对象如下:
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

从我标记开始到结束的信息原模原样转发给Plan subagent,你严禁私自添加任何内容,必须是我标记开始到结束的内容(标记了由你填写的地方你就根据你已知的内容填写):
===转发内容从这开始===
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

你的plan会在后续流程中被系统拆分给N个codex但你可以控制最多十个, 他们之间的信息并不互通是并发执行
Codex介绍: codex内置完整agent工具链如Bash使用、文件读取、网页浏览等
(注: codex属于外部工具, 一个task对应一个codex, 超出十个的task会被系统默认丢弃不会排队)

第一轮中你只会获得一个域名, 你不知道其他任何信息, 但是你可以规划信息收集任务给codex, 给出的域名就是目标, 严禁刻意子域名收集. 每下一轮都会返回上一轮codex的执行结果给你

===转发内容到这结束===

"""
