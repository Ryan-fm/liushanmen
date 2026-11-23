"""Compile and validate editable monitoring plans."""
import json
import os
import re
from urllib.request import Request, urlopen

from .i18n import copy, locale

NEWS_PROVIDERS = ("google", "bing")

SCENARIOS = {
    "sports": {
        "title": "赛事现场研判",
        "match": r"赛事|赛场|球迷|场馆|球赛|主场|验票|检票|赛程|球场|观众|入场",
        "topics": [
            {"label": "入场与票务", "terms": ["验票", "检票", "扫码", "入场", "闸机", "排队", "票务"], "owner": "场馆运营", "action": "对照票务记录和现场值班日志，核实入口、时段与影响范围。"},
            {"label": "交通与接驳", "terms": ["接驳", "停车", "拥堵", "交通", "散场"], "owner": "交通协调", "action": "核对接驳调度与现场记录，标明受影响路线和时段。"},
        ],
        "goal": "跟踪赛前至散场的现场反馈，发现重复出现的问题后核实位置与影响范围。",
    },
    "game": {
        "title": "游戏版本跟踪",
        "match": r"游戏|玩家|热修|steam|赛季更新|掉帧|读档|掉线",
        "topics": [
            {"label": "崩溃与登录", "terms": ["闪退", "崩溃", "登录失败", "黑屏", "掉线", "crash", "login failed"], "owner": "研发值班", "action": "比对版本、设备与复现步骤，核对是否为本次更新引入。"},
            {"label": "存档与进度", "terms": ["丢档", "存档", "读档", "进度回退", "save file"], "owner": "游戏运营", "action": "核对版本与账号范围，并在修复发布后检查新反馈。"},
        ],
        "goal": "发现版本发布后的新增问题，汇集复现线索并跟踪修复后的反馈。",
    },
    "brand": {
        "title": "新品口碑跟踪",
        "match": r"新品|投诉|售后|电商|消费者|供应链|退款|商品|漏水",
        "topics": [
            {"label": "商品质量", "terms": ["漏水", "破损", "异味", "不合格", "损坏", "质量"], "owner": "供应链", "action": "核对商品规格、订单和批次；按可用数据确认影响范围。"},
            {"label": "物流与售后", "terms": ["退货", "退款", "物流", "延迟", "发错", "补发"], "owner": "客服运营", "action": "核查工单和订单状态，集中处理同类问题。"},
        ],
        "goal": "从评价、客服与售后反馈中发现集中的问题，并持续观察处理后的变化。",
    },
    "business": {
        "title": "商机与公告跟踪",
        "match": r"招标|投标|公告|采购|截止日期|商机",
        "topics": [
            {"label": "新项目", "terms": ["招标公告", "竞争性磋商", "采购公告"], "owner": "商务团队", "action": "核对官方原文、地区、截止时间与资格条件。"},
            {"label": "变更与延期", "terms": ["更正", "延期", "终止", "补充公告"], "owner": "投标负责人", "action": "对照原公告，标明影响提交材料或截止时间的改动。"},
        ],
        "goal": "根据地区和关注对象发现新公告，并持续跟进相关更正信息。",
    },
}

EN_SCENARIOS = {
    "sports": {
        "title": "Venue and event monitoring",
        "match": r"\b(?:stadium|venue|matchday|home match|ticketing|ticket scans?|ticket scanning|turnstiles?|entry queues?|shuttle)\b",
        "topics": [
            {"label": "Entry and ticketing", "terms": ["ticket", "scan", "entry", "turnstile", "queue"],
             "owner": "Venue operations", "action": "Cross-check ticketing and venue logs for the affected gate, time, and scope."},
            {"label": "Transport and shuttles", "terms": ["shuttle", "parking", "congestion", "traffic"],
             "owner": "Transport operations", "action": "Compare dispatch and venue logs for the affected route and time."},
        ],
    },
    "game": {
        "title": "Game release monitoring",
        "match": r"\b(?:game|players?|hotfix|steam|crashes?|login failures?|game saves?|save files?|frame drops?)\b",
        "topics": [
            {"label": "Crashes and sign-in", "terms": ["crash", "login failed", "sign-in failure", "black screen", "disconnect"],
             "owner": "Engineering on call", "action": "Cross-check versions, devices, and reproduction steps."},
            {"label": "Saves and progress", "terms": ["save file", "lost save", "lost progress", "rollback"],
             "owner": "Game operations", "action": "Verify the affected versions and accounts and review feedback once a fix ships."},
        ],
    },
    "brand": {
        "title": "Product launch monitoring",
        "match": r"\b(?:product launch|customer feedback|customer complaints?|refunds?|returns?|e-commerce|leaks?|product quality|shipping delays?)\b",
        "topics": [
            {"label": "Product quality", "terms": ["leak", "broken", "damaged", "defect", "quality"],
             "owner": "Supply chain", "action": "Check product specifications, order records, and batch numbers."},
            {"label": "Delivery and after-sales", "terms": ["return", "refund", "delivery", "delay", "wrong item"],
             "owner": "Customer support", "action": "Review support tickets and order status for recurring problems."},
        ],
    },
    "business": {
        "title": "Tender and notice monitoring",
        "match": r"\b(?:tenders?|procurement|announcements?|bid deadlines?|requests? for proposals?)\b",
        "topics": [
            {"label": "New opportunities", "terms": ["tender notice", "procurement", "request for proposal"],
             "owner": "Business development", "action": "Check the official notice, region, deadline, and eligibility requirements."},
            {"label": "Changes and extensions", "terms": ["amendment", "extension", "postponement", "cancellation", "addendum"],
             "owner": "Bid manager", "action": "Compare the notices and note changes to materials or deadlines."},
        ],
    },
}
TIME_WINDOW = re.compile(r"(?:过去|近|最近|\b(?:past|last)\s+)\s*(\d{1,3})\s*(小时|天|hours?\b|days?\b)", re.I)
MINIMUM = re.compile(r"(?:(?:至少|超过|达到)\s*)?(\d{1,3})\s*(?:条|起|个独立|(?:distinct\s+)?(?:records?|reports?|articles?|complaints?|feedback items?)\b)", re.I)
OWNER = re.compile(r"(?:通知|提醒|交给|\b(?:notify|alert|assign to)\s+)([^，。；、\n,.;!?]{2,26})", re.I)


class InputError(ValueError):
    pass


def scenario_for(intent):
    scores = {key: len(re.findall(f'{value["match"]}|{EN_SCENARIOS[key]["match"]}', intent, re.I))
              for key, value in SCENARIOS.items()}
    return max(scores, key=scores.get) if any(scores.values()) else "general"


def string(value, field, maximum, required=False):
    if not isinstance(value, str):
        raise InputError(f"{field}必须是文本")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise InputError(f"{field}长度不符合要求（上限 {maximum} 字）")
    return value


def integer(value, field, low, high):
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 8:
        value = int(value)
    if type(value) is not int or not low <= value <= high:
        raise InputError(f"{field}须为 {low} 至 {high} 的整数")
    return value


def strings(value, field, limit, item_limit=80):
    if not isinstance(value, list) or len(value) > limit:
        raise InputError(f"{field}最多 {limit} 项")
    return list(dict.fromkeys(string(item, field, item_limit, True) for item in value))


def validate(plan, available_feeds):
    if not isinstance(plan, dict):
        raise InputError("方案须为结构化对象")
    lang = locale(plan.get("locale"))
    owner_default = copy(lang, "待分派", "Unassigned")
    raw_topics = plan.get("topics")
    if not isinstance(raw_topics, list) or not 1 <= len(raw_topics) <= 12:
        raise InputError("请配置 1 至 12 个研判主题")
    topics = []
    labels = set()
    for raw in raw_topics:
        if not isinstance(raw, dict):
            raise InputError("主题格式不正确")
        label = string(raw.get("label", ""), "主题名称", 48, True)
        if label.casefold() in labels:
            raise InputError(f"主题重复：{label}")
        labels.add(label.casefold())
        terms = strings(raw.get("terms", []), "关键词", 24)
        if not terms:
            raise InputError(f"{label} 至少需要一项关键词")
        topics.append({
            "label": label, "terms": terms,
            "owner": string(raw.get("owner", owner_default), "建议负责人", 64) or owner_default,
            "action": string(raw.get("action", ""), "核查动作", 260) or
                      copy(lang, "核对原始证据并确认影响范围。", "Review the original evidence and confirm the impact."),
        })
    feeds = strings(plan.get("feeds", []), "RSS 数据源", 12)
    if set(feeds) - set(available_feeds):
        raise InputError("方案包含未配置的 RSS 数据源")
    news_query = string(plan.get("news_query", ""), "公开新闻搜索词", 120)
    news_providers = strings(plan.get("news_providers", ["google"]), "公开搜索渠道", len(NEWS_PROVIDERS))
    if set(news_providers) - set(NEWS_PROVIDERS):
        raise InputError("公开新闻搜索渠道不正确。")
    if news_query and not news_providers:
        raise InputError("请至少选择一个公开新闻搜索渠道。")
    scenario = plan.get("scenario", "general")
    if scenario not in (*SCENARIOS.keys(), "general"):
        scenario = "general"
    return {
        "title": string(plan.get("title", ""), "任务名称", 64, True),
        "locale": lang,
        "goal": string(plan.get("goal", ""), "任务目标", 1000, True),
        "scenario": scenario,
        "entities": strings(plan.get("entities", []), "关注对象", 14),
        "topics": topics,
        "minimum": integer(plan.get("minimum", 3), "触发条数", 1, 1000),
        "channels": integer(plan.get("channels", 2), "交叉来源数", 1, 12),
        "hours": integer(plan.get("hours", 48), "回看小时数", 1, 2160),
        "cadence": integer(plan.get("cadence", 60), "检查间隔（分钟）", 5, 10080),
        "feeds": feeds,
        "news_query": news_query,
        "news_providers": news_providers,
        "generatedBy": "model" if plan.get("generatedBy") == "model" else "local",
    }


def template(intent, lang="zh-CN"):
    scenario = scenario_for(intent)
    base = copy(lang, SCENARIOS, EN_SCENARIOS).get(scenario)
    owner_default = copy(lang, "待分派", "Unassigned")
    # Quoted names are treated as suggested aliases. The user can change or clear them.
    named = re.findall(r'["「『“《]([^"」』”》]{1,36})["」』”》]', intent)
    explicit_topics = re.search(r"(?:关注|关键词|重点盯|keywords?|focus(?: on)?)\s*[:：]([^。；;\n]+)", intent, re.I)
    terms = [s.strip() for s in re.split(r"[,，、/]", explicit_topics.group(1)) if s.strip()] if explicit_topics else []
    has_chinese = bool(re.search(r"[\u3400-\u9fff]", intent))
    if base and not terms:
        matches = (SCENARIOS if has_chinese else EN_SCENARIOS)[scenario]["topics"]
        topics = [{**topic, "terms": match["terms"]} for topic, match in zip(base["topics"], matches, strict=True)]
    elif terms:
        topics = [
            {"label": term[:48], "terms": [term[:80]], "owner": owner_default,
             "action": copy(lang, "核对该主题的原始证据、发生时间和影响对象。", "Verify the original evidence, timing, and affected entities.")}
            for term in list(dict.fromkeys(terms))[:12]
        ]
    else:
        words = named or [segment[:12] for segment in re.split(r"[，。；！、\s]", intent) if len(segment) >= 2][:4]
        if not named and not has_chinese:
            stopwords = {"please", "help", "track", "monitor", "follow", "watch", "check", "the", "and", "about", "for", "with"}
            words = [word[:80] for word in re.findall(r"[\w-]{2,}", intent) if word.casefold() not in stopwords][:4] or [intent[:80]]
        topics = [{"label": copy(lang, "重点动态", "Key developments"), "terms": list(dict.fromkeys(words)),
                   "owner": owner_default, "action": copy(lang, "查看原始资料，确认变化是否满足用户目标。",
                                                        "Review the original evidence against the monitoring goal.")}]
    number = MINIMUM.search(intent)
    hours = TIME_WINDOW.search(intent)
    owner = OWNER.search(intent)
    if owner:
        topics = [{**topic, "owner": owner.group(1).strip()} for topic in topics]
    return {
        "title": base["title"] if base else copy(lang, "自定义情报跟踪", "Custom intelligence tracking"),
        "locale": lang,
        "goal": intent,
        "scenario": scenario,
        "entities": list(dict.fromkeys(named))[:14] if base else [],
        "topics": topics,
        "minimum": max(1, int(number.group(1))) if number else 3,
        "channels": 2,
        "hours": min(2160, max(1, int(hours[1]) * (24 if hours[2].lower() in ("天", "day", "days") else 1))) if hours else 48,
        "cadence": 30 if scenario == "sports" else 60,
        "feeds": [],
        "generatedBy": "local",
    }


def model_json(instructions, context):
    """Optional OpenAI-compatible endpoint configured by the local operator."""
    endpoint = os.environ.get("LSM_LLM_ENDPOINT")
    model = os.environ.get("LSM_LLM_MODEL")
    if not endpoint or not model:
        return None
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("LSM_LLM_KEY"):
        headers["Authorization"] = "Bearer " + key
    payload = {
        "model": model, "temperature": 0.2,
        "messages": [
            {"role": "system", "content": instructions + " 仅返回 JSON 对象，不使用 Markdown 围栏。"},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
    }
    try:
        request = Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urlopen(request, timeout=12) as result:
            response = json.loads(result.read(1024 * 1024))
        content = response["choices"][0]["message"]["content"].strip()
        content = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content)
        value = json.loads(content)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, KeyError, IndexError, AttributeError, TypeError):
        return None


def propose(intent, use_model, available_feeds, *, lang="zh-CN"):
    intent = string(intent, "监测需求", 1000, True)
    if len(intent) < 4:
        raise InputError("请补充关注对象或希望解决的问题")
    baseline = template(intent, lang)
    note = ""
    if use_model:
        candidate = model_json(
            "你是监测方案设计员。根据用户目标生成方案，沿用示例 JSON 字段。主题关键词要精确，"
            "负责人与检查频率可作建议。仅提取用户明确关注的实体作为筛选词，不编造数据源。"
            "案头推断不写成事实，feeds 固定为空。"
            + copy(lang, "用简体中文填写说明，关键词使用原始资料的语言。", "Write explanations in English. Use the evidence language for keywords."),
            {"intent": intent, "example": baseline},
        )
        if candidate:
            try:
                return validate({**baseline, **candidate, "locale": lang, "feeds": [], "generatedBy": "model"}, available_feeds), note
            except (InputError, TypeError):
                pass
        note = copy(lang, "模型未返回有效方案，已生成可编辑的本地草案。",
                    "The model returned an invalid plan. An editable local draft is ready.")
    return validate(baseline, available_feeds), note
