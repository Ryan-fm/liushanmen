from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app import Application
from intel.engine import Engine
from intel.f1_results import lookup_winner, parse_season, race_question
from intel.sources import feeds
from intel.store import Database


class OfficialF1ResultsTests(TestCase):
    def setUp(self):
        clock = patch("intel.f1_results.now", return_value=datetime(2026, 11, 23, tzinfo=timezone.utc))
        clock.start()
        self.addCleanup(clock.stop)

    def test_recognizes_direct_questions_without_rerouting_monitoring_or_sprints(self):
        self.assertEqual(race_question("拉斯维加斯站的冠军是谁"), ("las-vegas", (2026, 2025)))
        self.assertEqual(race_question("2025 年阿斯维加斯站谁赢了？"), ("las-vegas", (2025,)))
        self.assertEqual(race_question("Who won the British Grand Prix last year?"), ("great-britain", (2025,)))
        self.assertIsNone(race_question("跟踪拉斯维加斯站冠军的新闻"))
        self.assertIsNone(race_question("拉斯维加斯站冲刺赛的冠军是谁"))
        self.assertIsNone(race_question("谁是 F1 世界冠军"))

    def test_parses_winner_and_accepts_only_official_result_links(self):
        html = """
        <table><tr><th>Grand Prix</th><th>Date</th><th>Winner</th><th>Team</th><th>Laps</th><th>Time</th></tr>
        <tr><td><svg><title>Flag of the USA</title></svg>
        <a href="/en/results/2026/races/1300/las-vegas/race-result">Las Vegas</a></td>
        <td>21 Nov</td><td><span>Max</span><span>Verstappen</span><span>VER</span></td>
        <td>Red Bull Racing</td><td>50</td><td>1:27:39.624</td></tr>
        <tr><td><a href="https://other.example/en/results/2026/races/9999/miami/race-result">Miami</a></td>
        <td>03 May</td><td>One Driver DRV</td><td>Team</td><td>57</td><td>1:10:00.001</td></tr></table>
        """
        results = parse_season(html, 2026)
        self.assertEqual(set(results), {"las-vegas"})
        result = results["las-vegas"]
        self.assertEqual(result["driver"], "Max Verstappen")
        self.assertEqual(result["driver_zh"], "马克斯·维斯塔潘")
        self.assertEqual(result["url"], "https://www.formula1.com/en/results/2026/races/1300/las-vegas/race-result")

    def test_explicit_year_and_read_failures_do_not_substitute_another_season(self):
        prior = {"season": 2025, "driver": "Example Driver"}
        with patch("intel.f1_results.season_results", side_effect=lambda year: {"las-vegas": prior} if year == 2025 else {}):
            self.assertEqual(lookup_winner(("las-vegas", (2026, 2025)))["season"], 2025)
            explicit = lookup_winner(("las-vegas", (2026,)))
            self.assertEqual(explicit["status"], "not_found")
            self.assertEqual(explicit["season"], 2026)
        with patch("intel.f1_results.season_results", side_effect=OSError) as fetch:
            self.assertEqual(lookup_winner(("las-vegas", (2026, 2025)))["status"], "unavailable")
            fetch.assert_called_once_with(2026)

    def test_agent_question_returns_an_answer_without_creating_a_task(self):
        with TemporaryDirectory() as path:
            database = Database(Path(path) / "results.sqlite3")
            catalog = feeds()
            app = Application(database, Engine(database, catalog), catalog)
            events = []
            answer = {"status": "found", "driver": "Example Driver"}
            with patch("app.lookup_winner", return_value=answer):
                response = app.discover({"intent": "拉斯维加斯站的冠军是谁"},
                                        on_progress=lambda kind, data: events.append(kind))
            self.assertEqual(response, {"answer": answer})
            self.assertEqual(events, ["official_result_lookup"])
            self.assertEqual(database.index(), [])
