from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from intel.engine import Engine
from intel.inbox import build_inbox
from intel.rules import propose
from intel.sources import feeds, iso, normalize
from intel.store import Database


class InboxTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Database(Path(directory.name) / "inbox.sqlite3")
        self.catalog = feeds()
        self.at = datetime.fromisoformat("2026-11-22T18:00:00+00:00")

    def task(self, title, demo=False):
        plan, _ = propose("Track F1 news", False, self.catalog)
        plan.update(title=title, entities=["F1"], minimum=1, channels=1)
        plan["topics"][0]["terms"] = ["F1"]
        return self.db.create(plan, plan["goal"], demo=demo)

    def record(self, task, title, url, source, minutes_ago):
        item = normalize({"title": title, "text": title, "url": url,
                          "published_at": iso(self.at - timedelta(minutes=minutes_ago))},
                         default_source=source, default_kind="public")
        self.db.ingest(task, [item])
        return item

    def save_check(self, task, minutes_ago, sources=(), selected=None):
        self.db.set_active(task, True)
        task = self.db.task(task)
        candidates = []
        if selected:
            candidates = [Engine.combine(task["plan"]["topics"][0], [selected], task["plan"], [])]
        result = {"complete": [topic["label"] for topic in task["plan"]["topics"]], "sources": sources}
        self.db.save_run(task, "live", iso(self.at - timedelta(minutes=minutes_ago)), result, candidates)

    def inbox(self):
        return build_inbox(self.db, self.catalog, "zh-CN", at=self.at)

    def test_groups_related_reports_keeps_originals_and_uses_beijing_day(self):
        task = self.task("Formula 1")
        second = self.task("F1 sources")
        demo = self.task("Demo", demo=True)
        primary = self.record(task, "F1 FIA confirms Las Vegas safety car inquiry",
                              "https://example.test/inquiry", "Official", 40)
        self.record(second, "F1 Las Vegas safety car inquiry confirmed by FIA",
                    "https://other.example.test/story", "Reporter", 45)
        self.record(second, "F1 FIA confirms Las Vegas safety car inquiry",
                    "https://example.test/inquiry?utm_source=test", "Official", 50)
        self.record(task, "F1 race schedule released", "https://example.test/schedule", "Official", 3)
        self.record(task, "F1 previous day briefing", "https://example.test/previous", "Official", 121)
        self.record(demo, "F1 demo headline", "https://example.test/demo", "Demo", 4)
        self.save_check(task, 30, selected=primary)

        inbox = self.inbox()
        self.assertEqual(inbox["date"], "2026-11-23")
        self.assertEqual(inbox["task_count"], 2)
        self.assertEqual(len(inbox["stories"]), 2)
        story = inbox["stories"][0]
        self.assertTrue(story["priority"])
        self.assertEqual(story["sources"], 2)
        self.assertEqual(len(story["tasks"]), 2)
        self.assertEqual({report["url"] for report in story["reports"]},
                         {"https://example.test/inquiry", "https://other.example.test/story"})

    def test_puts_memory_hits_first_and_tracks_failure_recovery(self):
        task = self.task("Formula 1")
        self.db.add_memory(task, "关注：安全车")
        self.record(task, "F1 driver interview", "https://example.test/interview", "Official", 14)
        focus = self.record(task, "F1 safety car restart", "https://example.test/safety", "Official", 35)
        failed = {"id": "official", "source": "Official", "status": "failed", "note": "HTTP 503"}
        another = {"id": "reporter", "source": "Reporter", "status": "failed", "note": "HTTP 502"}
        self.save_check(task, 30, sources=[failed, another])
        self.save_check(task, 11, sources=[{**failed, "status": "ok", "note": "读取 1 条"}])

        inbox = self.inbox()
        self.assertEqual(inbox["stories"][0]["title"], focus["title"])
        self.assertEqual(inbox["stories"][0]["focus"], ["安全车"])
        self.assertEqual(inbox["sources_checked"], 2)
        active, recovered = inbox["failures"]
        self.assertEqual(active["source"], "Reporter")
        self.assertIsNone(active["recovered_at"])
        self.assertEqual(recovered["recovered_at"], iso(self.at - timedelta(minutes=11)))
