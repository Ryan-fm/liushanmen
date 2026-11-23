from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from app import Application
from intel.engine import Engine
from intel.rules import InputError, propose
from intel.sources import feeds, iso, normalize, now
from intel.store import Database


class RemoveTaskTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Database(Path(directory.name) / "remove.sqlite3")
        catalog = feeds()
        self.app = Application(self.db, Engine(self.db, catalog), catalog)
        self.plan, _ = propose("跟踪 F1 新闻", False, catalog)
        self.plan.update(minimum=1, channels=1)
        self.first = self.db.create(self.plan, "Track F1")
        self.second = self.db.create(self.plan, "Another task")
        self.record = normalize({"text": "Example evidence", "published_at": iso(now())},
                                default_source="Fixture", default_kind="public")

    def remove(self, confirmed):
        return self.app.handle("POST", ["tasks", self.first, "remove"], {"confirmed": confirmed})

    def test_removal_requires_confirmation(self):
        with self.assertRaises(InputError):
            self.remove(False)
        self.assertEqual(self.db.task(self.first)["id"], self.first)

    def test_removal_cascades_and_an_inflight_run_cannot_recreate_it(self):
        self.db.save_delivery_settings({"alerts": True, "daily": False, "time": "20:00", "locale": "zh-CN"})
        self.db.set_active(self.first, True)
        self.db.ingest(self.first, [self.record])
        self.db.ingest(self.second, [self.record])
        self.db.add_memory(self.first, "关注安全车")
        self.db.save_chat_turn(self.first, "测试", {"text": "示例回答"})
        self.db.save_dashboard_layout(self.first, {"title": "测试", "modules": ["trend"]})
        stale = self.db.task(self.first)
        candidate = Engine.combine(self.plan["topics"][0], [self.record], self.plan, [])
        result = {"complete": [candidate["label"]]}
        run = self.db.save_run(stale, "live", iso(now()), result, [candidate])
        self.assertEqual(self.db.pending_delivery(iso(now()))[0]["id"], "change:" + run)

        self.assertEqual(self.remove(True), {"removed": True})
        with self.db.connect() as connection:
            for table in ("evidence", "events", "runs", "task_memory", "task_chat", "task_dashboards"):
                self.assertFalse(connection.execute(f"SELECT 1 FROM {table} WHERE task_id=?", (self.first,)).fetchone())
        self.assertEqual(self.db.pending_delivery(iso(now())), [])
        self.assertEqual(len(self.db.records(self.second)), 1)
        with self.assertRaises(InputError):
            self.db.save_run(stale, "live", iso(now()), result, [candidate])
        with self.assertRaises(InputError):
            self.db.ingest(self.first, [self.record])
