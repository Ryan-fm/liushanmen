from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app import Application
from intel.engine import Engine
from intel.rules import propose
from intel.sources import feeds, iso, normalize, now
from intel.store import Database


class MemoryRankingTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Database(Path(directory.name) / "workspace.sqlite3")
        self.catalog = feeds()
        self.engine = Engine(self.db, self.catalog)
        self.app = Application(self.db, self.engine, self.catalog)

    def create_task(self, intent, *, demo=False, **changes):
        plan, _ = propose(intent, False, self.catalog)
        return self.db.create({**plan, **changes}, intent, demo=demo)

    def record(self, title, text, *, age, source, url=""):
        return normalize({"title": title, "text": text, "url": url,
                          "published_at": iso(now() - timedelta(hours=age))},
                         default_source=source, default_kind="public")

    def test_related_search_boosts_bilingual_focus_and_leaves_raw_records_intact(self):
        task = self.create_task("我想了解F1 比赛的新闻 给我检测")
        self.db.add_memory(task, "重点关注安全车和车手变动")
        unrelated = self.create_task("Track Le Mans news", entities=["Le Mans"])
        self.db.add_memory(unrelated, "Focus on: qualifying")
        demo = self.create_task("Track F1 news", demo=True)
        self.db.add_memory(demo, "Focus on: standings")
        regular = self.record("F1 qualifying and standings", "Latest results.", age=0,
                              source="Formula 1 官方", url="https://example.test/latest")
        safety = self.record("F1 safety-car restart explained", "A race analysis.", age=3,
                             source="Formula 1 官方", url="https://example.test/safety")
        driver = self.record("Who will drive for Haas in F1", "A lineup announcement.", age=2,
                             source="Motorsport.com", url="https://example.test/driver")

        events = []
        with patch("intel.sources.get_feed", side_effect=lambda config: [regular, safety]
                   if config["name"] == "Formula 1 官方" else [driver]):
            result = self.app.discover({"intent": "查F1新闻"},
                                       on_progress=lambda kind, data: events.append((kind, data)))
            self.app.news.confirm(result["preview"]["id"], result["plan"])

        preview = result["preview"]
        self.assertEqual(preview["memory_focus"], ["安全车", "车手变动"])
        self.assertEqual(preview["count"], 3)
        self.assertEqual({row["id"] for row in preview["items"][:2]}, {safety["id"], driver["id"]})
        self.assertFalse(preview["items"][2].get("memory_hits"))
        official = next(data for kind, data in events if kind == "source_result" and data["source"] == "Formula 1 官方")
        self.assertEqual(official["samples"][0]["memory_hits"], ["安全车"])
        new_task = self.db.index()[0]["id"]
        self.assertEqual(len(self.db.records(new_task)), 3)
        self.assertTrue(all("memory_hits" not in record for record in self.db.records(new_task)))

    def test_checks_use_current_task_memory_without_changing_rule_counts(self):
        task = self.create_task("跟踪 F1 比赛", entities=["F1"], minimum=2, channels=1,
                                topics=[{"label": "F1 比赛", "terms": ["比赛"], "owner": "赛事运营", "action": "核对报道"}])
        self.db.ingest(task, [
            self.record("F1 常规比赛", "比赛日程已更新。", age=1, source="Feed"),
            self.record("F1 safety car", "比赛暂停期间的快讯。", age=3, source="Feed"),
            self.record("F1 driver lineup", "Haas announced a roster change.", age=2, source="Feed"),
            self.record("IndyCar safety car", "比赛出现事故。", age=2, source="Feed"),
        ])
        before = self.engine.run(task, "trial")["result"]["candidates"][0]
        note = self.db.add_memory(task, "关注：安全车、车手变动")
        result = self.engine.run(task, "trial")["result"]
        after = result["candidates"][0]

        for key in ("count", "stage", "window_ids"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after["evidence"][0]["memory_hits"], ["安全车"])
        self.assertEqual(result["memory_review"]["count"], 2)
        self.assertTrue(any("车手变动" in item["memory_hits"] for item in result["memory_review"]["items"]))
        self.db.remove_memory(task, note["id"])
        self.assertNotIn("memory_review", self.engine.run(task, "trial")["result"])
