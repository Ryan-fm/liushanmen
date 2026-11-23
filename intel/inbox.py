"""Build today's local intelligence inbox from saved records and formal checks."""
from collections import Counter, defaultdict
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from .engine import matches_entities, record_text
from .memory import focus_from_memory, rank_by_memory, searchable_text
from .sources import CST, configured_sources, iso, normalize_text, now, web_url

STOP_WORDS = {
    "the", "for", "and", "after", "with", "from", "into", "will", "have", "has", "this", "that",
    "new", "f1", "formula", "news", "report", "reporting", "latest", "today", "update", "updates",
    "官方", "最新", "新闻", "报道", "关于", "今天", "今日", "消息", "动态",
}
TRACKING_PARAMS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid"}
TITLE_WORDS = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+")


def canonical_url(value):
    if not web_url(value):
        return ""
    parsed = urlsplit(value)
    query = [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
             if key.casefold() not in TRACKING_PARAMS and not key.casefold().startswith("utm_")]
    query.sort(key=lambda pair: pair[0])
    return parsed._replace(scheme="https", netloc=parsed.netloc.casefold(), fragment="",
                           path=parsed.path.rstrip("/") or "/", query=urlencode(query)).geturl()


def title_terms(title):
    terms = set()
    for word in TITLE_WORDS.findall(searchable_text(title)):
        if word[0].isascii():
            if len(word) > 2 and word not in STOP_WORDS:
                terms.add(word.rstrip("s") if len(word) >= 5 and word.endswith("s") and not word.endswith("ss") else word)
        else:
            terms.update(word[index:index + 2] for index in range(len(word) - 1)
                         if word[index:index + 2] not in STOP_WORDS)
    return terms


def report_keys(report):
    record = report["record"]
    keys = [("id", record["id"])]
    if link := canonical_url(record["url"]):
        keys.append(("url", link))
    if ref := record["reference"].strip().casefold():
        keys.append(("reference", report["task"]["id"], ref))
    if len(title := normalize_text(record["title"])) >= 8:
        keys.append(("title", title))
    if len(body := normalize_text(record["text"])) >= 20:
        keys.append(("body", body))
    return keys


def cluster_reports(reports):
    groups = []
    by_key = {}
    by_term = defaultdict(list)
    signatures = []
    years = []
    for report in reports:
        keys = report_keys(report)
        group = next((by_key[key] for key in keys if key in by_key), None)
        terms = title_terms(report["record"]["title"])
        dates = {term for term in terms if re.fullmatch(r"20\d{2}", term)}
        if group is None and len(terms) >= 3:
            candidates = Counter(index for term in terms for index in by_term[term])
            # Compare to the lead headline only to avoid chaining separate stories.
            for index, shared in sorted(candidates.items(), key=lambda pair: (-pair[1], pair[0])):
                if shared < 3:
                    break
                if dates and years[index] and dates.isdisjoint(years[index]):
                    continue
                other = signatures[index]
                if shared >= .65 * min(len(terms), len(other)) and shared >= .5 * max(len(terms), len(other)):
                    group = index
                    break
        if group is None:
            group = len(groups)
            groups.append([])
            signatures.append(terms)
            years.append(dates)
            for term in terms:
                by_term[term].append(group)
        groups[group].append(report)
        for key in keys:
            by_key.setdefault(key, group)
    return groups


def task_summary(task):
    return {"id": task["id"], "title": task["plan"]["title"]}


def event_summary(event, task):
    return {"id": event["id"], "task_id": task["id"], "label": event["label"],
            "status": event["status"], "at": event["updated_at"],
            "priority": event["stage"] == "alert" and event["status"] != "resolved"}


def article_summary(record):
    text = record.get("summary") or record["text"].removeprefix(record["title"] + "\n")
    return text[:360] if text != record["title"] else ""


def report_story(group):
    lead = next((row["record"] for row in group if row["record"]["title"]), group[0]["record"])
    tasks, events, focus, originals = {}, {}, {}, {}
    sources = set()
    for row in group:
        record = row["record"]
        tasks[row["task"]["id"]] = row["task"]
        for event in row["events"]:
            events[event["id"]] = event
        focus.update(dict.fromkeys(record.get("memory_hits", [])))
        sources.add(record["source"].casefold())
        key = canonical_url(record["url"]) or record["id"]
        originals.setdefault(key, {"id": record["id"], "task_id": row["task"]["id"],
                                    "title": record["title"], "source": record["source"], "url": record["url"],
                                    "published_at": record["published_at"], "published_missing": record.get("published_missing", False)})
    return {
        "title": lead["title"] or lead["text"][:100], "summary": article_summary(lead),
        "at": max([lead["published_at"], *[event["at"] for event in events.values()],
                   *[row["record"]["published_at"] for row in group]]),
        "tasks": list(tasks.values()), "events": list(events.values()), "focus": list(focus),
        "sources": len(sources), "reports": list(originals.values()),
        "priority": any(event["priority"] for event in events.values()),
    }


def event_story(event, task):
    details = event["history"][-1]["text"] if event.get("history") else event["explanation"]
    item = event_summary(event, task)
    return {"title": item["label"], "summary": details, "at": item["at"], "tasks": [task],
            "events": [item], "focus": [], "sources": 0, "reports": [], "priority": item["priority"]}


def source_health(tasks):
    latest = {}
    failed = {}
    for task in tasks:
        for check in task["checks"]:
            for source in check["sources"]:
                if source["status"] not in ("ok", "failed"):
                    continue
                key = (task["id"], source.get("id") or source["source"].casefold())
                reading = {**source, "task": task_summary(task), "at": check["at"], "run_id": check["id"]}
                latest[key] = reading
                if source["status"] == "failed":
                    failed[key] = reading
    failures = [{**reading, "recovered_at": latest[key]["at"] if latest[key]["status"] == "ok" else None}
                for key, reading in failed.items()]
    failures.sort(key=lambda item: (not item["recovered_at"], item["at"]), reverse=True)
    return len(latest), failures


def build_inbox(database, catalog, lang, *, at=None):
    instant = (at or now()).astimezone(CST)
    start = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    tasks = database.inbox_snapshot(start, instant)
    reports, event_updates = [], []
    for task in tasks:
        plan = task["plan"]
        summary = task_summary(task)
        selected = configured_sources(catalog, plan["feeds"], plan.get("news_query", ""), plan["hours"],
                                      plan.get("news_providers"))
        records = [record for record in task["records"]
                   if (not record.get("feed_id") or record["feed_id"] in selected)
                   and matches_entities(record_text(record), plan["entities"])]
        events_by_record = defaultdict(list)
        record_ids = {record["id"] for record in records}
        for event in task["events"]:
            associated = {record["id"] for record in event.get("evidence", [])} & record_ids
            if associated:
                item = event_summary(event, summary)
                for record_id in associated:
                    events_by_record[record_id].append(item)
            else:
                event_updates.append(event_story(event, summary))
        focus = focus_from_memory(task["notes"], lang)
        for record in rank_by_memory(records, focus):
            reports.append({"record": record, "task": summary, "events": events_by_record[record["id"]]})

    reports.sort(key=lambda row: (row["record"]["published_at"], row["record"]["id"]), reverse=True)
    stories = [report_story(group) for group in cluster_reports(reports)] + event_updates
    stories.sort(key=lambda item: (item["priority"], len(item["focus"]), item["at"], item["sources"]), reverse=True)
    sources_checked, failures = source_health(tasks)
    return {"date": instant.date().isoformat(), "as_of": iso(instant), "task_count": len(tasks),
            "sources_checked": sources_checked, "stories": stories, "failures": failures}
