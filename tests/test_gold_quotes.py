from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app import Application
from intel.engine import Engine
from intel.gold_quotes import SOURCE_ID, gold_price_request, parse_daily_prices
from intel.sources import feeds, iso, normalize, now
from intel.store import Database


class GoldQuotesTests(TestCase):
    def test_distinguishes_domestic_market_data_from_news_and_other_markets(self):
        self.assertTrue(gold_price_request("我想看一下最近黄金的走势"))
        self.assertTrue(gold_price_request("Au99.99 收盘价"))
        self.assertFalse(gold_price_request("黄金价格走势新闻"))
        self.assertFalse(gold_price_request("国际金价走势 XAUUSD"))
        self.assertFalse(gold_price_request("金店黄金多少钱"))

    def test_reads_auction_close_for_the_requested_instrument_and_date(self):
        html = """<table><tr><th>序号</th><th>日期</th><th>合约</th><th>开盘价</th>
        <th>最高价</th><th>最低价</th><th>收盘价</th></tr>
        <tr><td>1</td><td>2026-11-20</td><td>Au99.99</td><td>803.90</td><td>803.99</td><td>755.00</td><td>764.55</td></tr>
        <tr><td>2</td><td>2026-11-20</td><td>Au99.95</td><td>900</td><td>900</td><td>900</td><td>900</td></tr>
        <tr><td>3</td><td>2026-11-18</td><td>Au99.99</td><td>813</td><td>813</td><td>811</td><td>812</td></tr></table>"""
        rows = parse_daily_prices(html, date(2026, 11, 19), date(2026, 11, 23))
        self.assertEqual([row["quote"] for row in rows], [{"day": "2026-11-20", "close": "764.55"}])
        self.assertIn("www.sge.com.cn", rows[0]["url"])

    def test_market_preview_and_task_charts_use_only_the_gold_feed(self):
        catalog = feeds()
        with TemporaryDirectory() as folder:
            db = Database(Path(folder) / "gold.sqlite3")
            app = Application(db, Engine(db, catalog), catalog)
            row = normalize({"title": "Au99.99 daily close", "text": "Au99.99 daily close",
                             "url": "https://www.sge.com.cn/sjzx/quotation_daily_new",
                             "entity": "Au99.99", "published_at": iso(now())},
                            default_source="上海黄金交易所 · Au99.99", default_kind="public")
            row["quote"] = {"day": "2026-11-20", "close": "781.40"}
            with patch("intel.sources.get_feed", return_value=[row]) as feed:
                result = app.discover({"intent": "黄金最近的走势"})
            feed.assert_called_once()
            self.assertEqual(result["plan"]["feeds"], [SOURCE_ID])
            self.assertEqual(result["preview"]["market"]["quotes"][0]["close"], "781.40")
            self.assertEqual(db.index(), [])
            saved = app.news.confirm(result["preview"]["id"], result["plan"])
            self.assertIn("gold_price", app.handle("GET", ["tasks", saved["id"], "dashboard"], {})["modules"])
            self.assertEqual(db.insights(saved["id"])["gold_quotes"][0]["close"], "781.40")
