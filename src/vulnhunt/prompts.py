import json
def planner_prompt(goal, round_no, prior=None):
    return f"""
你的职责是Plan，有十个帮手可以随意使用，他们将作为你的"手"来执行。
你的任务是为漏洞挖掘规划出可行路径
你的目的是获取Critical/High漏洞

---

首轮你只会获得一个域名，之后的每一轮都会有你分配帮手数量的上一轮结果

目标：{goal}；
轮次：{round_no}；
上轮结果：{json.dumps(prior or [],ensure_ascii=False)}。
"""
