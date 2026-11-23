"""Read official Au99.99 daily closing prices from the Shanghai Gold Exchange."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from math import isfinite
import re
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .rules import InputError
from .sources import CST, NoRedirect, iso, normalize, now

SOURCE_ID = "sge-au9999"
SOURCE_NAME = "上海黄金交易所 · Au99.99"
INSTRUMENT = "Au99.99"
DAILY_URL = "https://www.sge.com.cn/sjzx/quotation_daily_new"
DAYS = 14
GOLD = re.compile(r"黄金|黃金|金价|金價|Au99\.99|\bgold\b", re.I)
QUOTE = re.compile(r"走势|走勢|金价|金價|行情|报价|報價|多少钱|多少錢|收盘|收盤|价格|價格|"
                   r"\b(?:price|prices|quote|closing|trend)\b", re.I)
OTHER_MARKET = re.compile(r"国际金价|國際金價|伦敦金|倫敦金|纽约金|紐約金|美元|盎司|ETF|金店|首饰|首飾|"
                          r"\b(?:XAUUSD|COMEX|USD|London|spot gold in dollars)\b", re.I)
NEWS = re.compile(r"新闻|新聞|资讯|資訊|报道|報道|\bnews\b", re.I)


def gold_price_request(intent):
    return bool(GOLD.search(intent) and QUOTE.search(intent) and not OTHER_MARKET.search(intent) and not NEWS.search(intent))


class DailyTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row, self.cell = [], None
        elif self.row is not None and tag in ("td", "th"):
            self.cell = []

    def handle_data(self, text):
        if self.cell is not None:
            self.cell.append(text)

    def handle_endtag(self, tag):
        if self.cell is not None and tag in ("td", "th"):
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif self.row is not None and tag == "tr":
            self.rows.append(self.row)
            self.row = None


def report_url(begin, end):
    return DAILY_URL + "?" + urlencode({"start_date": begin.isoformat(), "end_date": end.isoformat(), "inst_ids": INSTRUMENT})


def parse_daily_prices(html, begin, end):
    parser = DailyTable()
    parser.feed(html)
    parser.close()
    header = ["日期", "合约", "开盘价", "最高价", "最低价", "收盘价"]
    if not any(row[1:7] == header or row[:6] == header for row in parser.rows):
        raise InputError("上金所日行情表格无法识别")
    records = {}
    for row in parser.rows:
        fields = row[1:] if row and row[0].isdecimal() else row
        if len(fields) < 6 or fields[1] != INSTRUMENT:
            continue
        try:
            trade_day = date.fromisoformat(fields[0])
            close = Decimal(fields[5].replace(",", ""))
        except (InvalidOperation, ValueError):
            continue
        if not (begin <= trade_day <= end and close.is_finite() and close > 0 and isfinite(float(close))):
            continue
        day = trade_day.isoformat()
        price = format(close, "f")
        title = f"{INSTRUMENT} · {day} 收盘"
        summary = f"上海黄金交易所 {INSTRUMENT} 收盘价 {price} 元/克（交易日 {day}）。"
        record = normalize({"title": title, "text": summary, "url": report_url(trade_day, trade_day),
                            "entity": INSTRUMENT, "external_id": f"{INSTRUMENT}:{day}:{price}",
                            "published_at": iso(datetime.combine(trade_day, time.min, CST))},
                           default_source=SOURCE_NAME, default_kind="public")
        records[day] = {**record, "summary": summary, "quote": {"day": day, "close": price}}
    return [records[day] for day in sorted(records)]


def get_gold_feed():
    end = now().astimezone(CST).date()
    begin = end - timedelta(days=DAYS - 1)
    request = Request(report_url(begin, end), headers={"User-Agent": "Liushanmen/1.0", "Accept": "text/html"})
    with build_opener(NoRedirect).open(request, timeout=10) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise InputError("上金所日行情页面过大")
    return parse_daily_prices(payload.decode("utf-8"), begin, end)


def summarize_quotes(records):
    by_day = {}
    for item in records:
        quote = item.get("quote")
        if quote and item.get("feed_id") == SOURCE_ID:
            by_day[quote["day"]] = {**quote, "url": item["url"]}
    return [by_day[day] for day in sorted(by_day)][-DAYS:]
