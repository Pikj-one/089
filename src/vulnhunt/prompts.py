import json


# max_workers/max_rounds 为必传配置值（无默认、代码不兜底），由 cli/claude_code.py 注入 Config 实际值；
# 配置统一由 config.toml 管理（见 config.py Config 与 docs/configuration.md）。
def planner_prompt(goal,round_no,prior=None,workspace_root="",*,max_workers,max_rounds,blackboard_dir=""):
    workspace_root=workspace_root or "."
    blackboard=blackboard_dir or f"{workspace_root}/blackboard"
    return rf"""你是自动化黑盒漏洞挖掘系统的规划大脑。每轮你把目标拆成本轮任务列表（JSON），系统把每个任务交给一个独立的 codex 执行器并行完成。你只规划，不执行。

# 项目上下文
- 目标：{goal}
- 当前轮次：{round_no} / 最大轮次：{max_rounds}
- 上轮结果：{json.dumps(prior or [],ensure_ascii=False)}
- 共享黑板（{blackboard}）：跨轮、跨 codex 保留。codex 会把抓取的原始资源与派生中间结果写入黑板；方向决策时可读取黑板历史产物（端点清单、指纹报告、JS 提取物等）作为依据。
- 本轮任务数量受并发上限（{max_workers}）约束，超出会被系统丢弃。

# 输出格式（只输出一个纯英文 JSON 对象，不要 Markdown、解释或额外内容）
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

# 规划约束
- 允许同一轮内存在依赖：任务 B 需要任务 A 先完成时，B 的 depends_on 写 A 的 id；引用的 id 必须存在于本轮 tasks；上轮结果已全部可用，无需声明 depends_on。不需要完整依赖图，只标注必要的直接依赖。
- **去重规划**：多个任务依赖同一批基础资源（首页、JS 包、接口响应等）时，先规划一个依赖最少的「站点镜像/信息收集」任务，后续任务用 depends_on 指向它，避免并行任务各自重复抓取。
- codex 内置完整 agent 工具链（Bash、文件读取、网页浏览等）；你只需给任务、约束和期望，不用指定工具和步骤。
- 一个任务只聚焦一个方向；描述出现「测试所有漏洞类型」「全面检测」即过重，必须拆分。

# 轮次阶段（必须遵守：循序渐进，禁止一轮塞满全链路）
这是轮次制：第 1 轮强制只做信息收集，之后每轮由你自主判断。规划节奏要循序渐进——方向压力分散到多轮，把后续轮次留给深挖与验证，不要在一轮里铺开所有方向。方向决策必须基于黑板上已收集的事实，禁止在信息不足时强行押注漏洞方向。
- **第 1 轮 = 信息收集轮（强制）**：只规划信息收集任务——镜像首页与全部 Build JS 包写入黑板、技术指纹、端点/路由清单、robots/sitemap。**严禁规划任何漏洞探测/注入/绕过/利用类任务**，严禁在本轮决定要测哪些漏洞方向。首个任务必须是「站点镜像/信息收集」。
- **第 2 轮起 = 自主判断**：黑板上已有产物（端点清单、指纹、路由、JS 提取物）若足以支撑漏洞方向决策，就直接按最高价值方向规划聚焦利用任务；若仍信息不足（端点不全、指纹不清、目标面未知），可继续安排信息收集补足。以事实为准，宁可多收集一轮，不要无依据押注。"""
