import json
def planner_prompt(goal, round_no, prior=None):
    return f"你是漏洞挖掘 Planner。目标：{goal}；轮次：{round_no}；上轮结果：{json.dumps(prior or [],ensure_ascii=False)}。只输出 schema JSON。"
