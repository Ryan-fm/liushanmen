from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from intel.delivery import Delivery
from intel.engine import Engine
from intel.rules import propose
from intel.sources import feeds, iso, normalize
from intel.store import Database


class DeliveryTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Database(Path(directory.name) / "workspace.sqlite3")
        self.catalog = feeds()
        self.now = datetime.fromisoformat("2026-11-23T12:00:00+00:00")
        self.sent = []
        self.delivery = Delivery(self.db, self.catalog, notify=lambda title, body: self.sent.append((title, body)))
        self.plan, _ = propose("关注：安全车。跟踪 F1 比赛", False, self.catalog)
        self.plan.update(title="F1 watch", entities=["F1"], minimum=1, channels=1)
        self.task = self.db.create(self.plan, "F1 watch")
        self.db.set_active(self.task, True)
        self.record = normalize({"text": "F1 安全车复核启动", "title": "F1 安全车复核启动",
                                 "url": "https://example.test/report", "published_at": iso(self.now - timedelta(minutes=4))},
                                default_source="Test feed", default_kind="public")
        self.db.ingest(self.task, [self.record])

    def save_check(self, at, records, mode="live"):
        topic = self.plan["topics"][0]
        candidate = Engine.combine(topic, records[:], self.plan, [])
        result = {"complete": [topic["label"]], "sources": []}
        self.db.save_run(self.db.task(self.task), mode, iso(at), result, [candidate])

    def test_live_alerts_do_not_repeat_or_fire_for_trials(self):
        self.delivery.save_settings({"alerts": True, "daily": False, "time": "20:00"}, "en")
        self.save_check(self.now, [self.record], "trial")
        self.delivery.tick(self.now)
        self.assertEqual(self.sent, [])
        self.save_check(self.now, [self.record])
        self.delivery.tick(self.now)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Important update", self.sent[0][0])
        later = self.now + timedelta(minutes=10)
        self.save_check(later, [self.record])
        self.delivery.tick(later)
        self.assertEqual(len(self.sent), 1)
        self.db.status(self.task, self.db.detail(self.task)["events"][0]["id"], "resolved", "已处理")
        new = {**self.record, "text": "F1 安全车复核新增车队报告", "id": "another-record"}
        self.save_check(later, [self.record, new])
        self.delivery.tick(later)
        self.assertEqual(len(self.sent), 2)

    def test_daily_briefing_uses_beijing_time_and_survives_restart(self):
        self.delivery.save_settings({"alerts": False, "daily": True, "time": "20:00"}, "zh-CN")
        self.delivery.tick(self.now - timedelta(seconds=1))
        self.assertIsNone(self.db.latest_briefing())
        self.delivery.tick(self.now)
        self.assertEqual(len(self.sent), 1)
        briefing = self.db.latest_briefing()
        self.assertEqual(briefing["day"], "2026-11-23")
        self.assertIn("https://example.test/report", briefing["markdown"])
        self.assertEqual((self.delivery.directory / "2026-11-23.md").read_text(), briefing["markdown"])
        reopened = Delivery(Database(self.db.path), self.catalog,
                            notify=lambda title, body: self.sent.append((title, body)))
        reopened.tick(self.now + timedelta(minutes=15))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.db.latest_briefing()["created_at"], iso(self.now))

    def test_failed_notification_is_retried(self):
        self.delivery.save_settings({"alerts": True, "daily": False, "time": "20:00"}, "zh-CN")
        self.save_check(self.now, [self.record])

        def unavailable(title, body):
            raise OSError("notification service unavailable")

        broken = Delivery(self.db, self.catalog, notify=unavailable)
        broken.tick(self.now)
        self.assertEqual(broken.status()["last_error"], "desktop")
        self.delivery.tick(self.now + timedelta(minutes=1))
        self.assertEqual(self.sent, [])
        self.delivery.tick(self.now + timedelta(minutes=2))
        self.assertEqual(len(self.sent), 1)
        self.assertIsNone(self.delivery.status()["last_error"])
