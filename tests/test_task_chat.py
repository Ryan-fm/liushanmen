from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import quote

from app import Application
from intel.chat_model import CodexChatModel, chat_model, load_env, read_env
from intel.engine import Engine
from intel.gold_quotes import SOURCE_ID
from intel.memory import focus_from_memory
from intel.rules import propose
from intel.sources import feeds, iso, normalize, now
from intel.store import Database


class TaskChatTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Database(Path(directory.name) / "workspace.sqlite3")
        catalog = feeds()
        self.app = Application(self.db, Engine(self.db, catalog), catalog)
        self.task = self.create("跟踪 F1 新闻")
        self.other = self.create("跟踪量子计算新闻")
        self.f1 = self.evidence(self.task, "F1 Safety car projected timing change")
        self.quantum = self.evidence(self.other, "Quantum computing lab opened")

    def create(self, intent):
        plan, _ = propose(intent, False, self.app.feeds)
        return self.db.create(plan, intent)

    def evidence(self, task, title, *, hours_ago=0):
        timestamp = now() - timedelta(hours=hours_ago)
        record = normalize({"title": title, "text": title, "url": "https://example.test/" + quote(title),
                            "published_at": iso(timestamp)}, default_source="Example", default_kind="public")
        self.db.ingest(task, [record])
        return record

    def ask(self, task, question, **options):
        return self.app.handle("POST", ["tasks", task, "chat"], {"question": question, **options})["reply"]

    def test_replies_and_history_stay_within_the_selected_task(self):
        with patch("intel.task_chat.model_json") as model:
            answer = self.ask(self.task, "安全车有进展吗？")
            model.assert_not_called()
        self.assertEqual([item["target"] for item in answer["references"]], [self.f1["id"]])
        other_answer = self.ask(self.other, "安全车有进展吗？")
        self.assertEqual(other_answer["references"], [])
        self.assertEqual(len(Database(self.db.path).chat_history(self.task)), 1)

    def test_chat_remembers_preferred_name_and_reads_it_without_using_model(self):
        with patch("intel.task_chat.model_reply") as model:
            saved = self.ask(self.task, "我叫 Ryan 记一下")
            repeated = self.ask(self.task, "你记一下")
            recalled = self.ask(self.task, "你还记得我叫什么吗？")
            other = self.ask(self.other, "我叫什么？")
            model.assert_not_called()
        self.assertEqual(saved["mode"], "memory")
        self.assertEqual(saved["memory"]["text"], "称呼：Ryan")
        self.assertEqual(saved["memory"]["scope"], "workspace")
        self.assertEqual(repeated["memory"]["id"], saved["memory"]["id"])
        self.assertIn("Ryan", recalled["text"])
        self.assertIn("Ryan", other["text"])
        notes = Database(self.db.path).workspace_memories()
        self.assertEqual(notes[0]["id"], saved["memory"]["id"])
        self.assertEqual(self.db.memories(self.task), [])
        renamed = self.ask(self.task, "Remember: call me Taylor", useModel=False)
        self.assertEqual(renamed["memory"]["id"], saved["memory"]["id"])
        self.assertIn("Taylor", self.ask(self.task, "What's my name?")["text"])

    def test_memory_command_handles_an_explicit_note_and_requests_missing_content(self):
        ask_for_content = self.ask(self.other, "你记一下")
        self.assertNotIn("memory", ask_for_content)
        self.assertIn("记住什么", ask_for_content["text"])
        self.assertEqual(self.db.memories(self.other), [])

        saved = self.ask(self.task, "记住：关注：安全车、车手变动")
        self.assertEqual(saved["mode"], "memory")
        self.assertEqual(saved["memory"]["scope"], "task")
        self.assertEqual(list(focus_from_memory(self.db.memories(self.task), "zh-CN")), ["安全车", "车手变动"])
        read = self.ask(self.task, "查看当前任务记忆")
        self.assertEqual(read["points"][0]["text"], saved["memory"]["text"])

        shared = self.ask(self.task, "记住：回复尽量简短")
        self.assertEqual(shared["memory"]["scope"], "workspace")
        self.assertEqual(self.ask(self.other, "你记住了什么？")["points"][0]["text"], "回复尽量简短")

    def test_global_memory_is_available_to_other_tasks_models_and_can_be_removed(self):
        saved = self.ask(self.task, "记住：回答先讲结论")["memory"]
        self.ask(self.task, "任务记忆：关注安全车")
        self.app.chat_model_lookup = lambda: CodexChatModel("/fixture/codex", "")
        fake = {"points": [{"text": "你的偏好是先讲结论。", "ids": ["workspace_memory:" + saved["id"]]}],
                "limitation": ""}
        with patch("intel.task_chat.codex_reply", return_value=fake) as model:
            answer = self.ask(self.other, "我的回答偏好是什么？")
        context = model.call_args.args[2]
        self.assertEqual(context["workspace_memory"][0]["text"], "回答先讲结论")
        self.assertEqual(context["focus"], [])
        self.assertEqual(answer["references"][0]["kind"], "workspace_memory")
        self.db.remove_task(self.task)
        self.assertEqual(self.app.handle("GET", ["memory"], {})["notes"][0]["id"], saved["id"])
        self.app.handle("POST", ["memory", saved["id"]], {"text": "回复尽量简短"})
        self.assertEqual(self.ask(self.other, "查看全局记忆")["points"][0]["text"], "回复尽量简短")
        self.app.handle("POST", ["memory", saved["id"], "remove"], {})
        self.assertEqual(self.app.handle("GET", ["memory"], {})["notes"], [])

    def test_legacy_name_is_moved_to_global_memory_once(self):
        note = self.db.add_memory(self.task, "称呼：Ryan")
        focus = self.db.add_memory(self.task, "关注：安全车")
        with self.db.connect() as connection:
            connection.execute("DELETE FROM meta WHERE name='workspace_memory_v1'")
        migrated = Database(self.db.path)
        self.assertEqual(migrated.workspace_memories(), [note])
        self.assertEqual(migrated.memories(self.task), [focus])
        self.assertIn("Ryan", self.ask(self.other, "我叫什么？")["text"])
        migrated.remove_workspace_memory(note["id"])
        self.assertEqual(Database(self.db.path).workspace_memories(), [])

    def test_short_remember_can_save_a_previously_unhandled_name_request(self):
        self.db.save_chat_turn(self.task, "我叫 Ryan 记一下",
                               {"text": "No source for this question.", "points": [], "references": [], "mode": "model"})
        self.assertEqual(self.db.memories(self.task), [])
        result = self.ask(self.task, "你记一下")
        self.assertEqual(result["memory"]["text"], "称呼：Ryan")

    def test_follow_up_can_reuse_the_previous_evidence(self):
        self.ask(self.task, "安全车有进展吗？")
        follow_up = self.ask(self.task, "展开第一条")
        self.assertEqual(follow_up["references"][0]["target"], self.f1["id"])
        self.assertIn("Safety car", follow_up["points"][0]["text"])

    def test_short_followup_recovers_previous_topic_and_citations(self):
        original = "安全车有进展吗？"
        self.ask(self.task, original, useModel=False)
        for _ in range(5):
            self.db.save_chat_turn(self.task, "是谁", {"text": "旧版未找到。", "points": [],
                                                     "references": [], "mode": "local"})
        self.app.chat_model_lookup = lambda: CodexChatModel("/fixture/codex", "")
        fake = {"points": [{"text": "Based on the earlier safety car report.",
                            "ids": ["evidence:" + self.f1["id"]]}], "limitation": ""}
        with patch("intel.task_chat.codex_reply", return_value=fake) as provider:
            answer = self.ask(self.task, "是谁")
        context = provider.call_args.args[2]
        self.assertEqual(context["recent_dialogue"][0]["question"], original)
        self.assertEqual(context["evidence"][0]["id"], "evidence:" + self.f1["id"])
        self.assertEqual(answer["provider"], "codex")
        self.assertEqual(answer["references"][0]["target"], self.f1["id"])
        self.assertEqual(self.app.handle("GET", ["tasks", self.task, "chat"], {})["model"]["provider"], "codex")

    def test_date_scoped_updates_exclude_older_evidence(self):
        self.evidence(self.task, "F1 older schedule report", hours_ago=36)
        answer = self.ask(self.task, "今天有什么新进展？")
        self.assertEqual([item["target"] for item in answer["references"]], [self.f1["id"]])

    def test_summary_prioritizes_saved_interests_and_merges_duplicate_reports(self):
        self.db.add_memory(self.task, "关注：安全车")
        self.db.ingest(self.task, [{**self.f1, "id": "duplicate", "source": "Syndicated"}])
        self.evidence(self.task, "F1 driver lineup update")
        answer = self.ask(self.task, "今天有哪些重要变化？")
        titles = [item["label"] for item in answer["references"]]
        self.assertEqual(titles[0], self.f1["title"])
        self.assertEqual(titles.count(self.f1["title"]), 1)
        self.assertIn("F1 driver lineup update", titles)

    def test_model_rejects_references_outside_retrieved_evidence(self):
        fake = {"points": [{"text": "Uncited claim.", "ids": ["evidence:" + self.quantum["id"]]}]}
        with patch.dict("os.environ", {"LSM_TASK_LLM_ENDPOINT": "http://127.0.0.1:11434/v1/chat/completions",
                                      "LSM_TASK_LLM_MODEL": "test-model"}):
            with patch("intel.task_chat.model_json", return_value=fake) as model:
                answer = self.ask(self.task, "安全车有进展吗？")
                model.assert_called_once()
        self.assertEqual(answer["mode"], "local")
        self.assertEqual(answer["modelState"], "failed")
        self.assertEqual(answer["references"][0]["target"], self.f1["id"])

    def test_openai_compatible_chat_uses_env_key_and_task_context_by_default(self):
        requests = []

        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                context = json.loads(payload["messages"][1]["content"])
                requests.append((self.path, self.headers.get("Authorization"), payload["model"], context))
                result = {"points": [{"text": "上金所 Au99.99 收盘价为 781.40 元/克。",
                                      "ids": [context["evidence"][0]["id"]]}],
                          "limitation": "仅凭日收盘价无法判断买入是否适合。"}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode())

            def log_message(self, *_):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Provider) as server:
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                gold = self.create("跟踪黄金走势")
                saved = self.evidence(gold, "Au99.99 close")
                saved = {**saved, "id": "gold-quote", "feed_id": SOURCE_ID,
                         "quote": {"day": "2026-11-23", "close": "781.40"}}
                self.db.ingest(gold, [saved])
                self.db.add_memory(gold, "关注交易所每日收盘价")
                self.ask(gold, "今天有什么新进展？", useModel=False)
                endpoint = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
                with patch.dict("os.environ", {}, clear=True):
                    config = self.db.path.parent / ".env"
                    self.app.chat_model_lookup = lambda: chat_model(read_env(config))
                    self.assertIsNone(self.app.handle("GET", ["tasks", gold, "chat"], {})["model"])
                    config.write_text(f'LSM_TASK_LLM_ENDPOINT={endpoint}\nLSM_TASK_LLM_MODEL=test-model\n'
                                      'LSM_TASK_LLM_KEY="fixture-key"\n', encoding="utf-8")
                    answer = self.ask(gold, "你判断一下能不能买")
                    chat = self.app.handle("GET", ["tasks", gold, "chat"], {})
                    config.unlink()
                    self.assertIsNone(self.app.handle("GET", ["tasks", gold, "chat"], {})["model"])
                path, auth, model, context = requests[0]
                self.assertEqual((path, auth, model), ("/v1/chat/completions", "Bearer fixture-key", "test-model"))
                self.assertEqual(context["question"], "你判断一下能不能买")
                self.assertEqual(context["evidence"][0]["quote"]["close"], "781.40")
                self.assertEqual(context["recent_dialogue"][0]["question"], "今天有什么新进展？")
                self.assertEqual(context["focus"], ["关注交易所每日收盘价"])
                self.assertNotIn(self.quantum["id"], json.dumps(context))
                self.assertEqual(answer["mode"], "model")
                self.assertEqual(answer["references"][0]["target"], saved["id"])
                self.assertEqual(chat["model"], {"name": "test-model", "local": True})
                self.assertNotIn("fixture-key", json.dumps(chat))
            finally:
                server.shutdown()
                worker.join()

    def test_openai_key_stays_with_openai_and_env_does_not_override_process(self):
        config = self.db.path.parent / ".env"
        config.write_text("OPENAI_API_KEY=file-key\nOPENAI_MODEL=fixture-model\n", encoding="utf-8")
        with patch.dict("os.environ", {"OPENAI_API_KEY": "process-key"}, clear=True):
            load_env(config)
            self.assertEqual(chat_model().key, "process-key")
            with patch.dict("os.environ", {"LSM_TASK_LLM_ENDPOINT": "https://provider.example/v1/chat/completions",
                                          "LSM_TASK_LLM_MODEL": "another-model"}):
                self.assertIsNone(chat_model())
                with patch.dict("os.environ", {"LSM_TASK_LLM_KEY": "provider-key"}):
                    self.assertEqual(chat_model().key, "provider-key")
                    self.assertFalse(chat_model().local)

    def test_latest_run_failure_question_links_to_the_run(self):
        self.db.set_active(self.task, True)
        run = self.db.save_run(self.db.task(self.task), "live", iso(now()), {"complete": [],
            "sources": [{"source":"Working", "status":"ok","note":"读取 1 条"},
                        {"source":"Broken", "status":"failed","note":"HTTP 503"}]}, [])
        answer = self.ask(self.task, "有哪些来源读取失败？")
        self.assertEqual(answer["references"][0]["target"], run)
        self.assertEqual(len(answer["points"]), 1)
        self.assertIn("HTTP 503", answer["points"][0]["text"])
