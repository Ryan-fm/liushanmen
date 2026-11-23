"""Discover public news and keep a short-lived evidence preview until confirmation."""
from datetime import timedelta
import re
from threading import Lock
from uuid import uuid4

from .i18n import copy
from .rules import MINIMUM, OWNER, TIME_WINDOW, InputError, validate
from .sources import collect_sources, configured_sources, date, iso, normalize_text, now

F1 = re.compile(r"(?<!\w)f\s*1(?![a-z0-9])|formula\s*(?:one|1)|一级方程式", re.I)
NEWS = re.compile(r"新闻|资讯|报道|赛况|头条|公开动态|比赛结果|赛果")
NEWS_EN = re.compile(r"\b(?:news|headlines|press coverage|race reports?|race results?|public updates)\b", re.I)
PRIVATE = re.compile(r"私域|内部|工单|客服|售后|退款|手机号|@|https?://|"
                     r"\b(?:internal|private|confidential|support tickets?|customer support|refunds?|phone numbers?)\b", re.I)


def subject_from(intent):
    chinese, english = NEWS.search(intent), NEWS_EN.search(intent)
    if not (chinese or english) or PRIVATE.search(intent):
        return None
    if F1.search(intent):
        return "F1", '"Formula 1"', ("f1-official", "f1-motorsport")
    quoted = re.search(r'[「“《"]([^」”》"]{2,60})[」”》"]', intent)
    if quoted:
        subject = quoted[1]
    elif chinese:
        prefix = intent[:chinese.start()]
        subject = re.split(r"[，。；！？\n]", prefix)[-1].strip()
        subject = re.sub(r"^(?:(?:我想|请你|请|先|帮我|给我|查一下|查找|搜索|看看|看一下|监测|跟踪|关注|了解|关于|近期|最新|最近的?)\s*)+", "", subject)
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
    return subject, subject, ()


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


def highlight(items, limit=8):
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


class NewsDiscovery:
    def __init__(self, database, catalog):
        self.database = database
        self.catalog = catalog
        self._pending = {}
        self._lock = Lock()

    def inspect(self, intent, draft, subject, *, on_progress=None):
        label, search_term, direct = subject
        lang = draft.get("locale", "zh-CN")
        hours = draft["hours"] if TIME_WINDOW.search(intent) else 168
        keys = [key for key in direct if key in self.catalog]
        query = "" if keys else search_term

        def source_result(entry, batch):
            found = preview_items(batch, hours, now())
            samples = [{field: item[field] for field in ("title", "url", "source")} for item in found[:2]]
            on_progress("source_result", {**entry, "matched": len(found), "samples": samples})

        def search(feed_keys, search_query):
            selected = configured_sources(self.catalog, feed_keys, search_query, hours)
            if on_progress is not None:
                on_progress("checking_sources", {"hours": hours, "sources": [
                    {"id": key, "source": config["name"]} for key, config in selected.items()
                ]})
            return collect_sources(selected, on_result=source_result if on_progress is not None else None, lang=lang)

        records, logs = search(keys, query)
        nowish = now()
        items = preview_items(records, hours, nowish)
        with_results = {record["feed_id"] for record in items}
        working = [key for key in keys if key in with_results]
        if keys and not items:
            # Keep the failed source statuses visible; try broad search for this public subject.
            query = search_term
            fallback, fallback_logs = search([], query)
            logs.extend(fallback_logs)
            nowish = now()
            items = preview_items(fallback, hours, nowish)

        if on_progress is not None:
            on_progress("summarizing", {})

        aliases = ["F1", "Formula 1", "Formula One", "一级方程式"] if label == "F1" else [label]
        explicit_minimum = bool(re.search(r"至少\s*\d+\s*条|\bat least\s+\d+", intent, re.I) and MINIMUM.search(intent))
        title_suffix = copy(lang, " 新闻跟踪", " News Monitoring")
        topic_suffix = copy(lang, " 新闻", " News")
        plan = validate({
            **draft, "title": label[:64 - len(title_suffix)] + title_suffix,
            "scenario": "sports" if label == "F1" else draft["scenario"],
            "entities": aliases, "topics": [{
                "label": label[:48 - len(topic_suffix)] + topic_suffix, "terms": aliases,
                "owner": draft["topics"][0]["owner"] if OWNER.search(intent) else copy(lang, "待分派", "Unassigned"),
                "action": copy(lang, "查看报道原文和来源，核对新进展是否与已跟踪事件相关。",
                               "Open the original reporting and check how the new developments relate to tracked events."),
            }],
            "minimum": draft["minimum"] if explicit_minimum else 1, "channels": 1, "hours": hours,
            "cadence": 60, "feeds": working or ([] if query else keys), "news_query": query, "generatedBy": "local",
        }, self.catalog)
        key = uuid4().hex
        with self._lock:
            self._pending = {token: value for token, value in self._pending.items() if value["expires"] > nowish}
            if len(self._pending) >= 32:
                self._pending.pop(next(iter(self._pending)))
            self._pending[key] = {"intent": intent, "items": items, "expires": nowish + timedelta(minutes=30)}
        return plan, {
            "id": key, "label": label, "checked_at": iso(nowish), "count": len(items),
            "items": highlight(items), "sources": logs,
        }

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
            selected = configured_sources(self.catalog, plan["feeds"], plan["news_query"], plan["hours"])
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
