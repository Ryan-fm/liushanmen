"""Discover public news and keep a short-lived evidence preview until confirmation."""
from datetime import timedelta
import re
from threading import Lock
from uuid import uuid4

from .i18n import copy
from .gold_quotes import DAILY_URL, DAYS as GOLD_DAYS, summarize_quotes
from .memory import focus_from_memory, phrase_pattern, rank_by_focus, searchable_text
from .rules import MINIMUM, NEWS_PROVIDERS, OWNER, TIME_WINDOW, InputError, validate
from .sources import collect_sources, configured_sources, date, iso, normalize_text, now

F1 = re.compile(r"(?<![a-z0-9])(?:f\s*1|formula\s*(?:one|1))(?![a-z0-9])|一级方程式", re.I)
F1_ALIASES = ("F1", "Formula 1", "Formula One", "一级方程式")
F1_FEEDS = ("f1-official", "f1-motorsport", "f1-bbc", "f1-espn", "f1-the-race", "f1-racefans")
TOPIC_FEEDS = {
    ("NBA", "美职篮", "美職籃"): ("nba-espn",),
    ("足球", "Soccer", "Association football"): ("football-bbc", "football-espn"),
    ("体育", "體育", "Sports"): ("rthk-sports",),
    ("OpenAI",): ("openai",),
    ("Hugging Face", "HuggingFace"): ("huggingface",),
    ("NASA", "美国宇航局", "美國太空總署"): ("nasa",),
    ("美联储", "美聯儲", "Federal Reserve", "The Federal Reserve", "The Fed"): ("federal-reserve",),
    ("大中华", "大中華", "Greater China"): ("rthk-china",),
    ("财经", "財經", "Finance"): ("rthk-finance",),
}
TOPIC_LOOKUP = {normalize_text(alias): (aliases, keys)
                for aliases, keys in TOPIC_FEEDS.items() for alias in aliases}
NEWS = re.compile(r"新闻|资讯|报道|赛况|头条|公开动态|比赛结果|赛果")
NEWS_EN = re.compile(r"\b(?:news|headlines|press coverage|race reports?|race results?|public updates)\b", re.I)
PRIVATE = re.compile(r"私域|内部|工单|客服|售后|退款|手机号|@|https?://|"
                     r"\b(?:internal|private|confidential|support tickets?|customer support|refunds?|phone numbers?)\b", re.I)
TITLE_RACE = re.compile(r"世界冠军|世界冠軍|车手总冠军|車手總冠軍|总冠军|總冠軍|冠军争夺|冠軍爭奪|争冠|爭冠|"
                        r"\b(?:world champion(?:ship)?|drivers?[’']? championship|title race|title fight|WDC)\b", re.I)
QUESTION = re.compile(r"谁|誰|是什么|是什麼|[?？]|\b(?:who|what|why|how)\b", re.I)
MONITOR_TOPICS = [(keys, tuple((alias, phrase_pattern(alias)) for alias in aliases))
                  for aliases, keys in TOPIC_FEEDS.items()]
CHAMPIONSHIP_FOCUS = (
    ("冠军争夺",
     ("世界冠军", "世界冠軍", "车手总冠军", "冠军争夺", "总冠军", "world champion",
      "world championship", "drivers' championship", "drivers’ championship", "title race", "title fight", "title battle")),
    ("车手积分",
     ("车手积分", "积分榜", "积分差", "standings", "driver points", "points gap")),
    ("关键赛果",
     ("正赛结果", "赛果", "分站冠军", "race result", "race winner", "wins")),
)


def subject_from(intent):
    chinese, english = NEWS.search(intent), NEWS_EN.search(intent)
    if not (chinese or english) or PRIVATE.search(intent):
        return None
    if F1.search(intent):
        return "F1", '"Formula 1"', F1_FEEDS
    quoted = re.search(r'[「“《"]([^」”》"]{2,60})[」”》"]', intent)
    if quoted:
        subject = quoted[1]
    elif chinese:
        prefix = intent[:chinese.start()]
        subject = re.split(r"[，。；！？\n]", prefix)[-1].strip()
        subject = re.sub(r"^(?:(?:我想|请你|请|先|帮我|给我|查一下|查找|查|搜索|看看|看一下|看|监测|跟踪|关注|了解|关于|近期|最新|最近的?)\s*)+", "", subject)
        subject = re.sub(r"(?:\s|的|相关|最新|比赛)+$", "", subject)
    else:
        after = re.match(r"\s+(?:about|on|for|regarding)\s+(.+)", intent[english.end():], re.I)
        if after:
            subject = re.split(r"[.!?,;]|\s+(?:in|over|from) the (?:past|last)\b", after[1], maxsplit=1, flags=re.I)[0]
        else:
            subject = re.sub(
                r"^(?:(?:please|can you|could you|help me|i want to|find|track|follow|monitor|show me|look up|"
                r"search for|give me|get|the|latest|recent|public)\s+)+", "", intent[:english.start()].strip(), flags=re.I)
        subject = subject.strip(" .!?")
    if not 2 <= len(subject) <= 60 or not re.search(r"[\u3400-\u9fffA-Za-z]", subject):
        return None
    return subject, subject, TOPIC_LOOKUP.get(normalize_text(subject), ((), ()))[1]


def news_scope(intent, *, monitoring=False):
    subject = subject_from(intent)
    championship = bool(F1.search(intent) and TITLE_RACE.search(intent))
    inferred = False
    if subject is None and not PRIVATE.search(intent):
        text = searchable_text(intent)
        if championship and (monitoring or not QUESTION.search(intent)):
            subject = ("F1", '"Formula 1"', F1_FEEDS)
        elif monitoring and not QUESTION.search(intent):
            choices = []
            if F1.search(text):
                choices.append(("F1", '"Formula 1"', F1_FEEDS))
            for keys, aliases in MONITOR_TOPICS:
                matches = [alias for alias, pattern in aliases if pattern.search(text)]
                if matches:
                    label = max(matches, key=len)
                    choices.append((label, label, keys))
            if len(choices) == 1:
                subject = choices[0]
        inferred = subject is not None
    if not subject or not (inferred or championship):
        return subject, None
    topics = CHAMPIONSHIP_FOCUS if championship else ()
    return subject, {"label": subject[0], "topics": [label for label, _ in topics],
                     "terms": [term for _, terms in topics for term in terms],
                     "ranking": {label: tuple(phrase_pattern(term) for term in terms) for label, terms in topics}}


def aliases_for(label):
    if label == "F1":
        return F1_ALIASES
    return TOPIC_LOOKUP.get(normalize_text(label), ((label,), ()))[0]


def task_matches_subject(task, label):
    plan = task["plan"]
    aliases = aliases_for(label)
    keys = {normalize_text(alias) for alias in aliases}
    targets = [*plan.get("entities", []), plan.get("news_query", "")]
    targets = [target for target in targets if target]
    if targets:
        return any(normalize_text(target) in keys for target in targets)
    for value in (task["intent"], plan["goal"], plan["title"]):
        inferred = subject_from(value)
        if inferred:
            if normalize_text(inferred[0]) in keys:
                return True
        else:
            text = searchable_text(value)
            if any(phrase_pattern(alias).search(text) for alias in aliases):
                return True
    return False


def preview_items(records, hours, captured_at):
    lower = captured_at - timedelta(hours=hours)
    candidates = [
        record for record in records
        if record["title"] and record["url"] and lower <= date(record["published_at"]) <= captured_at
    ]
    # A feed without publication dates is sorted in its published feed order.
    candidates.sort(key=lambda record: record["published_at"], reverse=True)
    items = []
    links = set()
    headlines = set()
    for record in candidates:
        headline = normalize_text(record["title"])
        if record["url"] not in links and headline not in headlines:
            links.add(record["url"])
            headlines.add(headline)
            items.append(record)
    return items


def highlight_by_source(items, limit):
    selected = []
    seen = set()
    for item in items:
        if item["source"] not in seen:
            seen.add(item["source"])
            selected.append(item)
            if len(selected) == min(limit, 3):
                break
    ids = {item["id"] for item in selected}
    selected.extend(item for item in items if item["id"] not in ids)
    return selected[:limit]


def highlight(items, limit=8):
    scoped = [item for item in items if item.get("scope_hits")]
    preferred = [item for item in items if not item.get("scope_hits") and item.get("memory_hits")]
    other = [item for item in items if not item.get("scope_hits") and not item.get("memory_hits")]
    selected = []
    for tier in (scoped, preferred, other):
        if len(selected) == limit:
            break
        selected.extend(highlight_by_source(tier, limit - len(selected)))
    return selected


class NewsDiscovery:
    def __init__(self, database, catalog):
        self.database = database
        self.catalog = catalog
        self._pending = {}
        self._lock = Lock()

    def inspect(self, intent, draft, subject, *, scope=None, market=False, on_progress=None):
        label, search_term, direct = subject
        lang = draft.get("locale", "zh-CN")
        hours = GOLD_DAYS * 24 if market else draft["hours"] if TIME_WINDOW.search(intent) else 168
        keys = [key for key in direct if key in self.catalog]
        query = "" if label == "F1" and keys else search_term
        notes = (note for task in self.database.tasks_with_memories()
                 if task_matches_subject(task, label) for note in task["notes"])
        focus = focus_from_memory(notes, lang)
        scope_info = {"label": scope["label"], "topics": scope["topics"]} if scope else None
        if scope_info and on_progress is not None:
            on_progress("news_scope", scope_info)

        def rank(items):
            ranked = rank_by_focus(items, focus)
            return rank_by_focus(ranked, scope["ranking"], match_key="scope_hits") if scope else ranked

        def source_result(entry, batch):
            found = preview_items(batch, hours, now())
            samples = [{"title": item["title"], "url": item["url"], "source": item["source"],
                        "memory_hits": item.get("memory_hits", []), "scope_hits": item.get("scope_hits", [])}
                       for item in rank(found)[:2]]
            on_progress("source_result", {**entry, "matched": len(found), "samples": samples})

        def search(feed_keys, search_query):
            selected = configured_sources(self.catalog, feed_keys, search_query, hours, NEWS_PROVIDERS)
            if on_progress is not None:
                on_progress("checking_sources", {"hours": hours, "memory_focus": list(focus), "sources": [
                    {"id": key, "source": config["name"]} for key, config in selected.items()
                ]})
            return collect_sources(selected, on_result=source_result if on_progress is not None else None, lang=lang)

        records, logs = search(keys, query)
        nowish = now()
        items = preview_items(records, hours, nowish)
        with_results = {record["feed_id"] for record in items}
        working = [key for key in keys if key in with_results]
        if keys and not market and not query and not items:
            # Keep the failed source statuses visible; try broad search for this public subject.
            query = search_term
            fallback, fallback_logs = search([], query)
            logs.extend(fallback_logs)
            nowish = now()
            items = preview_items(fallback, hours, nowish)

        if on_progress is not None:
            on_progress("summarizing", {})

        aliases = list(aliases_for(label))
        explicit_minimum = bool(re.search(r"至少\s*\d+\s*条|\bat least\s+\d+", intent, re.I) and MINIMUM.search(intent))
        title_suffix = copy(lang, " 新闻跟踪", " News Monitoring")
        topic_suffix = copy(lang, " 新闻", " News")
        plan = validate({
            **draft, "title": copy(lang, "黄金价格跟踪", "Gold price monitoring") if market else label[:64 - len(title_suffix)] + title_suffix,
            "scenario": "sports" if label == "F1" else draft["scenario"],
            "entities": aliases, "topics": [{
                "label": copy(lang, "黄金收盘行情", "Gold daily close") if market else label[:48 - len(topic_suffix)] + topic_suffix,
                "terms": scope["terms"] if scope and scope["terms"] else aliases,
                "owner": draft["topics"][0]["owner"] if OWNER.search(intent) else copy(lang, "待分派", "Unassigned"),
                "action": copy(lang, "查看报道原文和来源，核对新进展是否与已跟踪事件相关。",
                               "Open the original reporting and check how the new developments relate to tracked events."),
            }],
            "minimum": draft["minimum"] if explicit_minimum else 1, "channels": 1, "hours": hours,
            "cadence": 60, "feeds": working or ([] if query else keys), "news_query": query,
            "news_providers": list(NEWS_PROVIDERS), "generatedBy": "local",
        }, self.catalog)
        key = uuid4().hex
        with self._lock:
            self._pending = {token: value for token, value in self._pending.items() if value["expires"] > nowish}
            if len(self._pending) >= 32:
                self._pending.pop(next(iter(self._pending)))
            self._pending[key] = {"intent": intent, "items": items, "expires": nowish + timedelta(minutes=30)}
        preview = {
            "id": key, "label": label, "checked_at": iso(nowish), "count": len(items),
            "items": highlight(rank(items)), "sources": logs, "memory_focus": list(focus), "scope": scope_info,
        }
        if market:
            preview["market"] = {"quotes": summarize_quotes(items), "url": DAILY_URL}
        return plan, preview

    def confirm(self, key, raw_plan):
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key):
            raise InputError("请先查看一轮新闻预览")
        with self._lock:
            entry = self._pending.get(key)
            if entry is None or entry["expires"] <= now():
                raise InputError("新闻预览已过期，请重新查询后确认")
            if entry.get("task_id"):
                return self.database.detail(entry["task_id"])
            plan = validate(raw_plan, self.catalog)
            selected = configured_sources(self.catalog, plan["feeds"], plan["news_query"], plan["hours"],
                                          plan["news_providers"])
            if not selected:
                raise InputError("请至少选择一个数据来源或填写公开新闻搜索词")
            with self.database.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                task_id = self.database.create(plan, entry["intent"], connection=conn)
                self.database.ingest(task_id, (item for item in entry["items"] if item["feed_id"] in selected),
                                     connection=conn)
                next_at = iso(now() + timedelta(minutes=plan["cadence"]))
                conn.execute("UPDATE tasks SET active=1,next_at=? WHERE id=?", (next_at, task_id))
            entry["task_id"] = task_id
            return self.database.detail(task_id)
