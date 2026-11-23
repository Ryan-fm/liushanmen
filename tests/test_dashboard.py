from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from app import Application
from intel.dashboard import CHARTS, apply_instruction, infer_dashboard
from intel.engine import Engine
from intel.rules import InputError, propose
from intel.sources import feeds, iso, normalize, now
from intel.store import Database


class DashboardTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Database(Path(directory.name) / "dashboards.sqlite3")
        catalog = feeds()
        self.app = Application(self.db, Engine(self.db, catalog), catalog)
        self.price = self.create("我想了解最近黄金的金价")
        self.sports = self.create("F1 世界冠军")

    def create(self, goal):
        plan, _ = propose(goal, False, self.app.feeds)
        return self.db.create(plan, goal)

    def dashboard(self, key, body=None, preview=False):
        path = ["tasks", key, "dashboard"] + (["preview"] if preview else [])
        return self.app.handle("GET" if body is None else "POST", path, body or {})

    def test_automatic_layout_changes_with_task_goal(self):
        gold = self.dashboard(self.price)
        f1 = self.dashboard(self.sports)
        self.assertEqual(gold["title"], "黄金价格跟踪")
        self.assertEqual(gold["modules"][:2], ["gold_price", "latest"])
        self.assertTrue(gold["price"])
        self.assertEqual(f1["title"], "F1 新闻跟踪")
        self.assertIn("冠军争夺", f1["focus"])
        self.assertNotEqual(gold["modules"], f1["modules"])

    def test_preview_is_reversible_and_settings_are_task_local(self):
        before = self.dashboard(self.price)
        other = self.dashboard(self.sports)
        revision = self.db.task(self.price)["revision"]
        proposal = self.dashboard(self.price, {"instruction": "我希望都是图"}, preview=True)
        self.assertEqual(proposal["modules"], ["gold_price", *CHARTS])
        self.assertEqual(self.dashboard(self.price), before)
        saved = self.dashboard(self.price, {"title": "我的行情面板", "modules": proposal["modules"]})
        self.assertTrue(saved["custom"])
        self.assertEqual(self.dashboard(self.price)["title"], "我的行情面板")
        self.assertEqual(self.dashboard(self.sports), other)
        self.assertEqual(self.db.task(self.price)["revision"], revision)
        self.assertEqual(self.dashboard(self.price, {"reset": True}), before)

    def test_instruction_reorders_and_hides_only_supported_modules(self):
        auto = infer_dashboard(self.db.task(self.price), "zh-CN")
        arranged = apply_instruction(auto, "把来源分布放最前面，隐藏记忆")
        self.assertEqual(arranged["modules"][0], "sources")
        self.assertNotIn("memory", arranged["modules"])
        self.assertEqual(apply_instruction(auto, "只看检查趋势和事件状态")["modules"], ["trend", "event_chart"])
        charts = apply_instruction(auto, "都是图，来源分布放第一")
        self.assertEqual(charts["modules"][0], "sources")
        self.assertEqual(set(charts["modules"]), {"gold_price", *CHARTS})
        with self.assertRaises(InputError):
            self.dashboard(self.price, {"title": "坏配置", "modules": ["not-a-widget"]})

    def test_charts_use_saved_evidence_counts(self):
        item = normalize({"title": "Example evidence", "text": "Example evidence", "published_at": iso(now())},
                         default_source="Example source", default_kind="public")
        self.db.ingest(self.price, [item])
        charts = self.db.insights(self.price)
        self.assertEqual(sum(day["count"] for day in charts["activity"]), 1)
        self.assertEqual(charts["recent"][0]["id"], item["id"])
        self.assertEqual(sum(day["count"] for day in self.db.insights(self.sports)["activity"]), 0)
