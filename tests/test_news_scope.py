from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app import Application
from intel.engine import Engine
from intel.news import news_scope
from intel.sources import feeds, iso, normalize, now
from intel.store import Database


class NewsScopeTests(TestCase):
    def test_new_monitoring_recognizes_known_topics_without_news_keywords(self):
        self.assertEqual(news_scope("F1", monitoring=True)[0][0], "F1")
        self.assertEqual(news_scope("NBA 交易", monitoring=True)[0][0], "NBA")
        self.assertEqual(news_scope("OpenAI 模型发布", monitoring=True)[0][0], "OpenAI")
        self.assertIsNone(news_scope("跟踪 OpenAI 的内部工单", monitoring=True)[0])
        self.assertIsNone(news_scope("NBA 和 OpenAI 最新动态", monitoring=True)[0])

    def test_f1_championship_scope_is_shown_before_fetch_and_prioritizes_matching_reports(self):
        timestamp = now()
        older = iso(timestamp - timedelta(hours=2))
        newer = iso(timestamp - timedelta(minutes=20))
        articles = [
            normalize({"title": "F1 unveils a new livery", "text": "F1 details.",
                       "url": "https://example.test/livery", "published_at": newer},
                      default_source="Source", default_kind="public"),
            normalize({"title": "F1 driver standings shift", "text": "The world championship remains open.",
                       "url": "https://example.test/standings", "published_at": older},
                      default_source="Source", default_kind="public"),
        ]
        with TemporaryDirectory() as path:
            db = Database(Path(path) / "news.sqlite3")
            catalog = feeds()
            app = Application(db, Engine(db, catalog), catalog)
            events = []
            with patch("intel.sources.get_feed", return_value=articles) as fetch:
                response = app.discover({"intent": "F1 世界冠军", "mode": "monitor"},
                                        on_progress=lambda kind, data: events.append((kind, data)))

            self.assertEqual(events[0][0], "news_scope")
            self.assertEqual(events[1][0], "checking_sources")
            self.assertEqual(len(events[1][1]["sources"]), fetch.call_count)
            self.assertEqual(response["preview"]["scope"]["topics"], ["冠军争夺", "车手积分", "关键赛果"])
            self.assertEqual(response["preview"]["count"], 2)
            first = response["preview"]["items"][0]
            self.assertEqual(first["url"], "https://example.test/standings")
            self.assertIn("车手积分", first["scope_hits"])
            self.assertEqual(response["plan"]["goal"], "F1 世界冠军")
            self.assertIn("standings", response["plan"]["topics"][0]["terms"])
            self.assertEqual(db.index(), [])
