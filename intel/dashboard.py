"""Infer and validate per-task overview layouts without editing monitoring rules."""
import re

from .i18n import copy
from .gold_quotes import gold_price_request
from .news import news_scope
from .rules import InputError, string, strings

CHARTS = ("trend", "activity", "sources", "event_chart")
MODULE_ALIASES = {
    "metrics": r"监测指标|指标|\b(?:metrics|stats)\b",
    "trend": r"检查趋势|运行趋势|\b(?:check history|check trend)\b",
    "activity": r"证据增量|证据活动|采集趋势|\b(?:evidence activity|daily records)\b",
    "sources": r"来源分布|信源|来源|\b(?:source distribution|sources)\b",
    "event_chart": r"事件状态|事件图|\b(?:event status|event chart)\b",
    "gold_price": r"黄金走势|价格走势|收盘走势|金价走势|\b(?:gold trend|price trend)\b",
    "latest": r"最新证据|报价资料|最近报道|最新进展|报道|\b(?:latest evidence|latest reports)\b",
    "events": r"事件列表|待处理事件|\b(?:event list|open events)\b",
    "chat": r"任务问答|问答|对话|\b(?:task chat|chat)\b",
    "memory": r"记忆|\bmemory\b",
    "rules": r"当前规则|监测规则|规则|\brules\b",
}
ALL_CHARTS = re.compile(r"都是图|全是图|全图模式|纯图表|只看图表|只看图|只要图表|只要图|仅看图表|只放图表|"
                        r"全部用图|全部是图|全用图|全图|\b(?:charts? only|only charts?|all charts?)\b", re.I)
PRICE = re.compile(r"金价|黄金|报价|价格|行情|\b(?:gold|price|pricing|quote)\b", re.I)
HIDE = re.compile(r"隐藏|去掉|不要|不显示|收起|\b(?:hide|remove)\b", re.I)
ONLY = re.compile(r"只看|只显示|只要|仅保留|\bonly show\b", re.I)


def infer_dashboard(task, lang):
    plan = task["plan"]
    title = plan["title"]
    goal = plan["goal"]
    subject, scope = news_scope(goal, monitoring=True)
    price = bool(PRICE.search(goal))
    gold = gold_price_request(goal) or "sge-au9999" in plan["feeds"]
    focus = scope["topics"] if scope else [subject[0]] if subject else []
    if title in ("自定义情报跟踪", "Custom intelligence tracking"):
        if price and re.search(r"黄金|金价|\bgold\b", goal, re.I):
            title = copy(lang, "黄金价格跟踪", "Gold Price Monitoring")
        elif subject:
            title = subject[0] + copy(lang, " 新闻跟踪", " News Monitoring")
    if ALL_CHARTS.search(goal):
        modules = list(CHARTS)
    elif price:
        modules = ["latest", "sources", "activity", "chat", "memory", "rules"]
    elif subject:
        modules = ["metrics", "latest", "trend", "sources", "events", "memory", "rules"]
    elif plan["scenario"] != "general":
        modules = ["metrics", "events", "latest", "trend", "sources", "memory", "rules"]
    else:
        modules = ["metrics", "trend", "memory", "sources", "rules", "events"]
    if gold:
        modules.insert(0, "gold_price")
    return {"title": title[:64], "modules": modules, "focus": focus, "price": price, "gold": gold, "custom": False}


def validate_layout(payload):
    title = string(payload.get("title"), "概览标题", 64, True)
    modules = strings(payload.get("modules"), "概览模块", len(MODULE_ALIASES))
    if not modules or set(modules) - MODULE_ALIASES.keys():
        raise InputError("请选择至少一个可用的概览模块。")
    return {"title": title, "modules": modules}


def apply_instruction(layout, instruction):
    charts_only = bool(ALL_CHARTS.search(instruction))
    front, hidden = [], set()
    for clause in re.split(r"[,，;；。\n]", instruction):
        matches = []
        for key, pattern in MODULE_ALIASES.items():
            if match := re.search(pattern, clause, re.I):
                matches.append((match.start(), key))
        keys = [key for _, key in sorted(matches)]
        if HIDE.search(clause):
            hidden.update(keys)
        else:
            front.extend(keys)
    if not (charts_only or front or hidden):
        raise InputError("请指定想查看的模块，例如「只看图表」或「来源分布放最前面」。")
    if charts_only:
        remaining = (["gold_price"] if layout.get("gold") else []) + list(CHARTS)
        front = [key for key in front if key in remaining]
    else:
        remaining = [] if ONLY.search(instruction) and front else layout["modules"]
    modules = [key for key in dict.fromkeys(front + remaining) if key not in hidden]
    if not modules:
        raise InputError("请选择至少一个可用的概览模块。")
    return {**layout, "modules": modules}
