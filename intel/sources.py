"""Normalize evidence from user files and administrator-configured RSS/Atom feeds."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import json
import os
import re
import xml.etree.ElementTree as ET

from .rules import InputError, string
from .i18n import copy

UTC = timezone.utc
CST = timezone(timedelta(hours=8))
KINDS = {"internal": "客户自有资料", "public": "公开资料", "media": "媒体文字稿"}
BUILTIN_FEEDS = {
    "f1-official": {"name": "Formula 1 官方", "url": "https://www.formula1.com/en/latest/all.xml",
                    "entry_host": "www.formula1.com", "entry_prefix": "/en/latest/article/", "entity": "F1", "group": "f1"},
    "f1-motorsport": {"name": "Motorsport.com", "url": "https://www.motorsport.com/rss/f1/news/",
                      "entry_host": "www.motorsport.com", "entry_prefix": "/f1/news/", "entity": "F1", "group": "f1"},
    "f1-autosport": {"name": "Autosport · F1", "url": "https://www.autosport.com/rss/f1/news/",
                     "entry_host": "www.autosport.com", "entry_prefix": "/f1/news/", "entity": "F1", "group": "f1"},
    "f1-bbc": {"name": "BBC Sport · F1", "url": "https://feeds.bbci.co.uk/sport/formula1/rss.xml",
               "entry_host": "www.bbc.co.uk", "entry_prefix": "/sport/formula1/", "entity": "F1", "group": "f1"},
    "f1-espn": {"name": "ESPN · F1", "url": "https://www.espn.com/espn/rss/f1/news",
                "entity": "F1", "group": "f1"},
    "f1-racefans": {"name": "RaceFans · F1", "url": "https://www.racefans.net/category/formula-1/feed/",
                    "entry_host": "www.racefans.net", "entry_prefix": "/", "entity": "F1", "group": "f1"},
    "f1-the-race": {"name": "The Race · F1", "url": "https://www.the-race.com/rss/",
                    "entry_host": "www.the-race.com", "entry_prefix": "/formula-1/", "entity": "F1", "group": "f1"},
    "nba-espn": {"name": "ESPN · NBA", "url": "https://www.espn.com/espn/rss/nba/news", "entity": "NBA", "group": "sports"},
    "football-bbc": {"name": "BBC Sport · 足球", "url": "https://feeds.bbci.co.uk/sport/football/rss.xml",
                     "entity": "足球", "group": "sports"},
    "football-espn": {"name": "ESPN · 足球", "url": "https://www.espn.com/espn/rss/soccer/news",
                      "entity": "足球", "group": "sports"},
    "openai": {"name": "OpenAI 官方", "url": "https://openai.com/news/rss.xml", "entity": "OpenAI", "group": "tech"},
    "huggingface": {"name": "Hugging Face 博客", "url": "https://huggingface.co/blog/feed.xml",
                    "entity": "Hugging Face", "group": "tech"},
    "bbc-technology": {"name": "BBC 科技", "url": "https://feeds.bbci.co.uk/news/technology/rss.xml", "group": "tech"},
    "techcrunch": {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "group": "tech"},
    "federal-reserve": {"name": "美联储公告", "url": "https://www.federalreserve.gov/feeds/press_all.xml",
                        "entity": "美联储", "group": "finance"},
    "sge-au9999": {"name": "上海黄金交易所 · Au99.99", "url": "https://www.sge.com.cn/sjzx/quotation_daily_new",
                   "entity": "Au99.99", "group": "finance", "source_type": "sge_au9999"},
    "rthk-finance": {"name": "香港电台 · 财经", "url": "https://rthk9.rthk.hk/rthk/news/rss/c_expressnews_cfinance.xml",
                     "entity": "财经", "group": "finance"},
    "rthk-sports": {"name": "香港电台 · 体育", "url": "https://rthk9.rthk.hk/rthk/news/rss/c_expressnews_csport.xml",
                    "entity": "体育", "group": "sports"},
    "rthk-china": {"name": "香港电台 · 大中华", "url": "https://rthk9.rthk.hk/rthk/news/rss/c_expressnews_greaterchina.xml",
                   "entity": "大中华", "group": "news"},
    "arxiv-ai": {"name": "arXiv · AI 预印本", "url": "https://rss.arxiv.org/rss/cs.AI", "group": "research"},
    "nasa": {"name": "NASA 官方", "url": "https://www.nasa.gov/feed/", "entity": "NASA", "group": "research"},
    "python": {"name": "Python 发布记录", "url": "https://github.com/python/cpython/releases.atom", "group": "versions"},
    "bettafish": {"name": "BettaFish 发布记录", "url": "https://github.com/666ghj/BettaFish/releases.atom", "group": "versions"},
}


def now():
    return datetime.now(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="seconds")


def date(value, *, missing=None):
    if not value and missing:
        return missing
    if not isinstance(value, str) or not value.strip():
        raise InputError("证据必须有时间；请使用 ISO 8601 或 YYYY-MM-DD HH:MM")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value.strip())
        except (ValueError, TypeError, OverflowError) as error:
            raise InputError(f"无法识别时间：{value[:80]}") from error
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=CST)).astimezone(UTC)


def web_url(value):
    if not isinstance(value, str) or not value or re.search(r"[\s<>]", value):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        return ""
    return ""


def feeds():
    result = dict(BUILTIN_FEEDS)
    raw = json.loads(os.environ.get("LSM_FEEDS", "{}"))
    if not isinstance(raw, dict):
        raise ValueError("LSM_FEEDS 应为 JSON 对象")
    for key, config in raw.items():
        if not isinstance(config, dict) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,50}", key):
            raise ValueError("LSM_FEEDS 含不合法的 feed 标识")
        link = config.get("url", "")
        if not web_url(link) or not link.startswith("https://"):
            raise ValueError("RSS 配置必须是 HTTPS")
        result[key] = {"url": link, "name": string(config.get("name", key), "数据源名称", 100, True), "group": "custom"}
    return result


def normalize_text(value):
    return re.sub(r"[\W_]+", "", value.casefold())


def normalize(row, *, default_source, default_kind, synthetic=False):
    if not isinstance(row, dict):
        raise InputError("每条证据须为对象")
    body = string(row.get("text") or "", "证据原文", 12000, True)
    title = string(row.get("title") or "", "证据标题", 500)
    when = date(row.get("published_at") or row.get("timestamp"))
    source = string(row.get("source") or default_source, "来源", 100, True)
    kind = row.get("kind") or default_kind
    if not isinstance(kind, str) or kind not in KINDS:
        raise InputError("kind 只接受 internal、public 或 media")
    link = string(row.get("url") or "", "证据链接", 1500)
    if link and not web_url(link):
        raise InputError("证据链接只接受 HTTP 或 HTTPS")
    external = string(row.get("external_id") or "", "外部编号", 256)
    object_key = string(row.get("entity") or "", "证据对象", 128)
    independent_key = string(row.get("reference") or "", "订单或工单编号", 192)
    uniqueness = external or "\n".join((iso(when), link, title, body, independent_key))
    unique_id = sha256(f"{kind}\0{source.casefold()}\0{uniqueness}".encode()).hexdigest()
    return {
        "id": unique_id, "text": body, "title": title, "published_at": iso(when), "source": source, "kind": kind,
        "url": link, "entity": object_key, "reference": independent_key, "synthetic": synthetic,
    }


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_feed(config):
    if config.get("source_type") == "sge_au9999":
        from .gold_quotes import get_gold_feed
        return get_gold_feed()
    # URLs are only editable by the local operator via process configuration.
    # Do not follow redirects or accept URL inputs from browser requests.
    request = Request(config["url"], headers={"User-Agent": "Liushanmen-RSS/0.1"})
    with build_opener(NoRedirect).open(request, timeout=8) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise InputError("RSS 超过 2 MB")
    if re.search(br"<!\s*(DOCTYPE|ENTITY)\b", payload, re.I):
        raise InputError("RSS 包含不支持的 XML 声明")
    root = ET.fromstring(payload)
    entries = root.findall(".//{*}item") or root.findall(".//{*}entry")
    observed = now()
    records = []
    provider = config.get("news_provider", "")
    for entry in entries[:100]:
        def field(*keys):
            for key in keys:
                elem = entry.find("{*}" + key)
                if elem is not None:
                    result = "".join(elem.itertext()).strip()
                    if result:
                        return result
            return ""
        title = field("title")[:500]
        html = field("description", "summary", "content")
        parser = PlainHTML()
        parser.feed(html[:28000])
        summary = " ".join(" ".join(parser.text).split())
        body = (title + "\n" + summary).strip()[:12000]
        if not body:
            continue
        link = field("link")
        if not link:
            link = next((elem.get("href", "") for elem in entry.findall("{*}link")
                         if elem.get("rel", "alternate") == "alternate"), "")
        link = web_url(link)
        if provider == "bing" and link:
            parsed = urlsplit(link)
            if parsed.hostname == "www.bing.com" and parsed.path.casefold() == "/news/apiclick.aspx":
                link = web_url(parse_qs(parsed.query).get("url", [""])[0])
        if host := config.get("entry_host"):
            parsed = urlsplit(link)
            if parsed.hostname != host or not parsed.path.startswith(config["entry_prefix"]):
                continue
            link = parsed._replace(query="", fragment="").geturl()
        published = field("published", "pubDate", "updated", "date")
        external = field("guid", "id") or link or sha256(body.encode()).hexdigest()
        source = field("source", "Source")[:100] if provider else ""
        if provider == "google" and source and title.endswith(" - " + source):
            title = title.removesuffix(" - " + source)
            body = title
            summary = ""
        try:
            record = normalize({"title": title, "text": body, "url": link,
                                "published_at": iso(date(published, missing=observed)),
                                "external_id": external[:256], "entity": config.get("entity", "")},
                               default_kind="public", default_source=source or config["name"])
        except InputError:
            continue
        records.append({**record, "summary": summary[:380], "published_missing": not published,
                        "via_news_search": provider == "google", "news_provider": provider})
    return records


def configured_sources(catalog, keys, query="", hours=168, search_providers=None):
    selected = {key: catalog.get(key) for key in keys}
    if not query:
        return selected
    providers = ("google",) if search_providers is None else search_providers
    query_id = sha256(query.encode()).hexdigest()[:16]
    chinese = bool(re.search(r"[\u3400-\u9fff]", query))
    if "google" in providers:
        language = {"hl": "zh-Hant", "gl": "HK", "ceid": "HK:zh-Hant"} if chinese else {
            "hl": "en-US", "gl": "US", "ceid": "US:en"
        }
        options = {**language, "q": f"{query} when:{max(1, (hours + 23) // 24)}d"}
        selected["news-" + query_id] = {"name": f"Google 新闻 · {query}", "news_provider": "google",
                                       "url": "https://news.google.com/rss/search?" + urlencode(options)}
    if "bing" in providers:
        options = {"q": query, "format": "rss", "mkt": "zh-HK" if chinese else "en-US"}
        selected["bing-news-" + query_id] = {"name": f"Bing 新闻 · {query}", "news_provider": "bing",
                                           "url": "https://www.bing.com/news/search?" + urlencode(options)}
    return selected


def collect_sources(selected, *, on_result=None, lang="zh-CN"):
    results = {}

    def record_result(key, source, status, note, batch=()):
        records = [{**record, "feed_id": key} for record in batch]
        entry = {"id": key, "source": source, "status": status, "note": note}
        results[key] = records, entry
        if on_result is not None:
            on_result(entry, records)

    with ThreadPoolExecutor(max_workers=4) as workers:
        jobs = {workers.submit(get_feed, config): key for key, config in selected.items() if config}
        for key, config in selected.items():
            if config is None:
                record_result(key, key, "failed", copy(lang, "数据源已撤下", "Source removed from configuration"))
        for job in as_completed(jobs):
            key = jobs[job]
            source = selected[key]["name"]
            try:
                batch = job.result()
            except (URLError, OSError, ValueError, ET.ParseError, ImportError) as error:
                detail = f"HTTP {error.code}" if isinstance(error, HTTPError) else copy(lang, "连接或解析失败", "Could not connect or parse feed")
                if isinstance(error, ImportError):
                    detail = copy(lang, "Python 缺少 XML 解析组件", "Python XML parser is unavailable")
                record_result(key, source, "failed", detail)
            else:
                record_result(key, source, "ok", copy(lang, f"读取 {len(batch)} 条", f"Records read — {len(batch)}"), batch)
    # Return records and logs in configuration order, independently of request timing.
    return [record for key in selected for record in results[key][0]], [results[key][1] for key in selected]
