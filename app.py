"""六扇门, local inspection workstation. Python 3.11+; no external packages."""
import argparse
from collections import ChainMap
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
import os
from pathlib import Path
from threading import Event, Thread
from urllib.parse import parse_qs, urlsplit

from intel.chat_model import CodexChatModel, chat_model, load_env, read_env
from intel.dashboard import apply_instruction, infer_dashboard, validate_layout
from intel.demo import seed
from intel.delivery import Delivery
from intel.engine import Engine
from intel.f1_results import lookup_winner, race_question
from intel.gold_quotes import INSTRUMENT, SOURCE_ID, gold_price_request
from intel.i18n import copy, error_text, locale
from intel.inbox import build_inbox
from intel.memory import draft_from_memory
from intel.news import NewsDiscovery, news_scope
from intel.rules import InputError, integer, propose, string, template, validate
from intel.sources import KINDS, feeds, iso, normalize, now
from intel.store import Database, pack
from intel.task_chat import answer_task_question, memory_turn

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_PAYLOAD = 8 * 1024 * 1024
DISCOVERY_STREAM = "application/x-ndjson"
STATIC_ASSETS = {"/": "index.html", "/app.js": "app.js", "/i18n.js": "i18n.js",
                 "/styles.css": "styles.css", "/icon.png": "icon.png"}
STATUSES = {"open", "investigating", "resolved"}
LOGGER = logging.getLogger("liushanmen")


def model_configured():
    return bool(os.environ.get("LSM_LLM_ENDPOINT") and os.environ.get("LSM_LLM_MODEL"))


def write_report(task, lang="zh-CN"):
    def md(value):
        return value.replace("\r", "").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")

    def line(chinese, english, value):
        return f"- {copy(lang, chinese, english)}{' — ' if lang == 'en' else '：'}{value}"

    rows = [f"# {md(task['plan']['title'])}", "", copy(lang, "六扇门 · 情报简报", "Liushanmen Intelligence Brief"), "",
            line("任务目标", "Goal", md(task["plan"]["goal"])), line("当前方案版本", "Rule version", task["revision"])]
    if task["demo"]:
        rows.append(line("数据类型", "Data type", copy(lang, "合成演示样本", "Synthetic demo")))
    if task["runs"]:
        last = task["runs"][0]["result"]
        rows.append(line("最近观察窗口", "Latest lookback window", f"{last['window']['from']} – {last['window']['to']}"))
    rows.extend(["", copy(lang, "## 事件", "## Events"), ""])
    labels = copy(lang, {"open": "待核查", "investigating": "研判中", "resolved": "已处理"},
                        {"open": "Needs review", "investigating": "Investigating", "resolved": "Resolved"})
    for event in task["events"]:
        rows.extend([
            f"### {md(event['label'])}", "",
            line("状态", "Status", labels.get(event["status"], event["status"])),
            line("负责人", "Owner", md(event["owner"])),
            line("触发依据", "Why it triggered", md(event["explanation"])),
            line("复核建议", "Suggested review", md(event["action"])), "",
        ])
        if event.get("evidence_archived"):
            rows.append(copy(lang, "以下为上一轮保留的历史证据。", "Archived evidence from the previous run."))
        for evidence in event["evidence"]:
            link = f" <{evidence['url']}>" if evidence["url"] else ""
            rows.append(f"- {md(evidence['source'])} · {evidence['published_at']}{link} — {md(evidence['text'])}")
        rows.extend(["", copy(lang, "最近进展", "Recent updates"), ""])
        for entry in event["history"][-8:]:
            rows.append(f"- {entry['at']} · {md(entry['text'])}")
        rows.append("")
    if not task["events"]:
        rows.append(copy(lang, "当前任务尚无正式事件。", "No events have been recorded for this task."))
    return "\n".join(rows) + "\n"


class Application:
    def __init__(self, database, engine, configured_feeds, *, chat_model_lookup=chat_model):
        self.database = database
        self.engine = engine
        self.feeds = configured_feeds
        self.news = NewsDiscovery(database, configured_feeds)
        self.delivery = Delivery(database, configured_feeds)
        self.chat_model_lookup = chat_model_lookup

    def discover(self, body, *, on_progress=None, lang="zh-CN"):
        intent = string(body.get("intent"), "监测需求", 1000, True)
        if gold_price_request(intent):
            if on_progress is not None:
                on_progress("gold_quote_lookup", {})
            plan, preview = self.news.inspect(intent, template(intent, lang), (INSTRUMENT, "", (SOURCE_ID,)),
                                              market=True, on_progress=on_progress)
            return {"plan": plan, "preview": preview}
        if question := race_question(intent):
            if on_progress is not None:
                on_progress("official_result_lookup", {})
            return {"answer": lookup_winner(question)}
        subject, scope = news_scope(intent, monitoring=body.get("mode") == "monitor")
        if subject:
            plan, preview = self.news.inspect(intent, template(intent, lang), subject, scope=scope, on_progress=on_progress)
            return {"plan": plan, "preview": preview}
        plan, note = propose(intent, body.get("useModel") is True, self.feeds, lang=lang)
        return {"plan": plan, "note": note}

    def handle(self, method, path, body, *, lang="zh-CN"):
        db = self.database
        if path == ["memory"]:
            if method == "GET":
                return {"notes": db.workspace_memories()}
            if method == "POST":
                return db.add_workspace_memory(string(body.get("text"), "记忆内容", 2000, True))
        if method == "POST" and path[:1] == ["memory"] and len(path) >= 2:
            if len(path) == 2:
                return db.update_workspace_memory(path[1], string(body.get("text"), "记忆内容", 2000, True))
            if path[2:] == ["remove"]:
                db.remove_workspace_memory(path[1])
                return {"removed": True}
        if method == "GET" and path == ["inbox"]:
            return build_inbox(db, self.feeds, lang)
        if path == ["delivery"]:
            if method == "GET":
                return self.delivery.status()
            if method == "POST":
                return self.delivery.save_settings(body, lang)
        if method == "POST" and path == ["delivery", "test"]:
            return self.delivery.test(lang)
        if method == "GET" and path == ["meta"]:
            return {"feeds": [{"id": key, "name": value["name"], "group": value.get("group", "custom")}
                              for key, value in self.feeds.items()],
                    "modelConfigured": model_configured(),
                    "backgroundModel": model_configured() and os.environ.get("LSM_BACKGROUND_MODEL") == "1"}
        if method == "POST" and path == ["propose"]:
            plan, note = propose(body.get("intent"), body.get("useModel") is True, self.feeds, lang=lang)
            return {"plan": plan, "note": note}
        if method == "POST" and path == ["discover"]:
            return self.discover(body, lang=lang)
        if method == "POST" and path == ["news", "confirm"]:
            return self.news.confirm(body.get("preview_id"), body.get("plan"))
        if path == ["tasks"]:
            if method == "GET":
                return {"tasks": db.index()}
            if method == "POST":
                plan = validate(body.get("plan"), self.feeds)
                intent = string(body.get("intent", plan["goal"]), "原始需求", 1000)
                key = db.create(plan, intent)
                return db.detail(key)
        if len(path) < 2 or path[0] != "tasks":
            return None
        task_id = path[1]
        tail = path[2:]
        if method == "GET" and not tail:
            return db.detail(task_id)
        if method == "POST" and tail == ["remove"]:
            if body.get("confirmed") is not True:
                raise InputError("请确认删除该任务。")
            db.remove_task(task_id)
            return {"removed": True}
        if method == "GET" and tail == ["insights"]:
            return db.insights(task_id)
        if tail in (["dashboard"], ["dashboard", "preview"]):
            task = db.task(task_id)
            inferred = infer_dashboard(task, lang)
            saved = db.dashboard_layout(task_id)
            layout = {**inferred, **saved, "custom": True} if saved else inferred
            if method == "GET" and tail == ["dashboard"]:
                return layout
            if method == "POST" and tail == ["dashboard", "preview"]:
                instruction = string(body.get("instruction"), "布局需求", 500, True)
                if isinstance(body.get("layout"), dict):
                    layout = {**layout, **validate_layout(body["layout"])}
                return apply_instruction(layout, instruction)
            if method == "POST" and tail == ["dashboard"]:
                if body.get("reset") is True:
                    db.save_dashboard_layout(task_id, None)
                    return inferred
                changes = validate_layout(body)
                db.save_dashboard_layout(task_id, changes)
                return {**inferred, **changes, "custom": True}
        if tail == ["chat"]:
            if method == "GET":
                settings = self.chat_model_lookup()
                model = {"name": settings.name, "local": settings.local} if settings else None
                if isinstance(settings, CodexChatModel):
                    model["provider"] = "codex"
                return {"turns": db.chat_history(task_id), "model": model}
            if method == "POST":
                question = string(body.get("question"), "任务提问", 1000, True)
                if turn := memory_turn(db, task_id, question, lang):
                    return turn
                answer = answer_task_question(db, task_id, question, lang, use_model=body.get("useModel") is not False,
                                              model_lookup=self.chat_model_lookup)
                return db.save_chat_turn(task_id, question, answer)
        if tail == ["memory"]:
            if method == "GET":
                return {"notes": db.memories(task_id)}
            if method == "POST":
                return db.add_memory(task_id, string(body.get("text"), "记忆内容", 2000, True))
        if method == "POST" and tail[:1] == ["memory"] and len(tail) >= 2:
            note_id = tail[1]
            if len(tail) == 2:
                return db.update_memory(task_id, note_id, string(body.get("text"), "记忆内容", 2000, True))
            if tail[2:] == ["remove"]:
                db.remove_memory(task_id, note_id)
                return {"removed": True}
            if tail[2:] == ["draft"]:
                task = db.task(task_id)
                note = db.memory(task_id, note_id)
                return {"plan": draft_from_memory(task["plan"], note["text"], self.feeds), "revision": task["revision"]}
        if method == "GET" and tail == ["evidence"]:
            db.task(task_id)
            items = sorted(db.records(task_id), key=lambda item: item["published_at"], reverse=True)
            return {"count": len(items), "items": items[:150]}
        if method == "GET" and len(tail) == 2 and tail[0] == "evidence":
            db.task(task_id)
            return next((value for value in db.records(task_id) if value["id"] == tail[1]), None)
        if method == "POST" and tail == ["rules"]:
            raw_plan = body.get("plan")
            if isinstance(raw_plan, dict) and ("locale" not in raw_plan or "news_providers" not in raw_plan):
                previous = db.task(task_id)["plan"]
                raw_plan = {"locale": previous.get("locale"), "news_providers": previous.get("news_providers", ["google"]),
                            **raw_plan}
            plan = validate(raw_plan, self.feeds)
            revision = integer(body["revision"], "规则版本", 1, 2**31 - 1) if "revision" in body else None
            db.update_plan(task_id, plan, revision=revision)
            return db.detail(task_id)
        if method == "POST" and tail == ["active"]:
            active = body.get("active")
            if type(active) is not bool:
                raise InputError("请选择启用或暂停")
            db.set_active(task_id, active)
            return db.detail(task_id)
        if method == "POST" and tail == ["run"]:
            run = self.engine.run(task_id, body.get("mode"), body.get("asOf"), body.get("useModel") is True)
            return run
        if method == "POST" and tail == ["import"]:
            db.task(task_id)
            records = body.get("records")
            if not isinstance(records, list) or not 1 <= len(records) <= 3000:
                raise InputError("每次导入 1 至 3000 条记录")
            source = string(body.get("source", "文件导入"), "来源名称", 100, True)
            kind = body.get("kind", "internal")
            if not isinstance(kind, str) or kind not in KINDS:
                raise InputError("来源类型不正确")
            normalized = []
            for index, record in enumerate(records, start=1):
                try:
                    normalized.append(normalize(record, default_source=source, default_kind=kind))
                except InputError as error:
                    raise InputError(f"第 {index} 条：{error}") from error
            added = db.ingest(task_id, normalized)
            return {"added": added, "duplicates": len(records) - added}
        if method == "POST" and len(tail) == 3 and tail[0] == "events" and tail[2] == "status":
            status = body.get("status")
            if not isinstance(status, str) or status not in STATUSES:
                raise InputError("事件状态不正确")
            note = string(body.get("note", ""), "处理备注", 1000, True)
            db.status(task_id, tail[1], status, note)
            return db.detail(task_id)
        return None


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def begin_response(self, status, content_type, length=None, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if length is None:
                self.close_connection = True
                self.send_header("Connection", "close")
            else:
                self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                             "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()

        def respond(self, status, content, content_type, extra=None):
            self.begin_response(status, content_type, len(content), extra)
            if self.command != "HEAD":
                self.wfile.write(content)

        def json(self, status, value):
            self.respond(status, pack(value).encode(), "application/json; charset=utf-8")

        def stream_discovery(self, body, lang):
            self.begin_response(200, DISCOVERY_STREAM + "; charset=utf-8")

            def emit(event, data):
                self.wfile.write((pack({"type": event, "data": data}) + "\n").encode())
                self.wfile.flush()

            try:
                result = app.discover(body, on_progress=emit, lang=lang)
            except (BrokenPipeError, ConnectionResetError):
                return
            except ValueError as error:
                emit("error", {"error": error_text(str(error), lang)})
            except Exception:
                LOGGER.exception("Streaming discovery failed")
                emit("error", {"error": error_text("检索中断，请重试", lang)})
            else:
                emit("result", result)

        def permitted(self):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            host = self.headers.get("Host", "")
            if host.lower() not in allowed:
                return False
            origin = self.headers.get("Origin")
            return not origin or origin.lower() == f"http://{host.lower()}"

        def dispatch(self, method):
            lang = locale(self.headers.get("Accept-Language"))
            if not self.permitted():
                self.json(403, {"error": error_text("仅允许访问本地工作台", lang)})
                return
            url = urlsplit(self.path)
            path = url.path
            try:
                if method == "GET" and path in STATIC_ASSETS:
                    file = STATIC / STATIC_ASSETS[path]
                    content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                    if content_type.startswith(("text/", "application/javascript")):
                        content_type += "; charset=utf-8"
                    self.respond(200, file.read_bytes(), content_type)
                    return
                if not path.startswith("/api/"):
                    self.json(404, {"error": error_text("找不到页面", lang)})
                    return
                parts = path.removeprefix("/api/").strip("/").split("/")
                if method == "GET" and parts == ["briefings", "latest"]:
                    briefing = app.database.latest_briefing()
                    if briefing:
                        self.respond(200, briefing["markdown"].encode(), "text/markdown; charset=utf-8",
                                     {"Content-Disposition": f'attachment; filename="briefing-{briefing["day"]}.md"'})
                        return
                if method == "GET" and len(parts) == 3 and parts[0] == "tasks" and parts[2] == "report":
                    report_lang = locale(parse_qs(url.query).get("lang", [lang])[0])
                    report = write_report(app.database.detail(parts[1]), report_lang)
                    self.respond(200, report.encode(), "text/markdown; charset=utf-8",
                                 {"Content-Disposition": 'attachment; filename="liushanmen-report.md"'})
                    return
                body = {}
                if method == "POST":
                    if self.headers.get_content_type() != "application/json":
                        raise InputError("请求须为 JSON")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_PAYLOAD:
                        raise InputError("请求体为空或超过 8 MB")
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise InputError("请求 JSON 须为对象")
                    if parts == ["discover"] and self.headers.get("Accept") == DISCOVERY_STREAM:
                        self.stream_discovery(body, lang)
                        return
                value = app.handle(method, parts, body, lang=lang)
                if value is None:
                    self.json(404, {"error": error_text("找不到请求的资源", lang)})
                    return
                self.json(200, value)
            except (InputError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                self.json(400, {"error": error_text(str(error), lang)})
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                LOGGER.exception("Request failed: %s", path)
                self.json(500, {"error": error_text("处理失败，请在本地服务日志查看详情", lang)})

        def do_GET(self):
            self.dispatch("GET")

        def do_HEAD(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

        def log_message(self, format, *args):
            LOGGER.debug(format, *args)

    return Handler


def run_pending(app, stop):
    use_model = model_configured() and os.environ.get("LSM_BACKGROUND_MODEL") == "1"
    with ThreadPoolExecutor(max_workers=2) as executor:
        def run_one(key):
            try:
                app.engine.run(key, "live", use_model=use_model)
            except InputError as error:
                LOGGER.info("Background run deferred (%s): %s", key, error)
            except Exception:
                LOGGER.exception("Background run for %s failed", key)
                app.database.postpone(key, iso(now() + timedelta(minutes=5)))

        while not stop.wait(9):
            due = app.database.due(iso(now()))
            list(executor.map(run_one, due))


def run_delivery(app, stop):
    while not stop.wait(9):
        try:
            app.delivery.tick()
        except Exception:
            LOGGER.exception("Background delivery failed")


def main():
    env_path = ROOT / ".env"
    inherited = os.environ.copy()
    load_env(env_path)
    parser = argparse.ArgumentParser(description="六扇门本地情报工作台")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--db", default=ROOT / "data" / "liushanmen.sqlite3", type=Path)
    parser.add_argument("--empty", action="store_true", help="启动时不导入演示数据")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    db = Database(args.db)
    feed_catalog = feeds()
    engine = Engine(db, feed_catalog)
    application = Application(db, engine, feed_catalog,
                              chat_model_lookup=lambda: chat_model(ChainMap(inherited, read_env(env_path))))
    if not args.empty:
        seed(db, engine, feed_catalog)
    stop = Event()
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(application)) as server:
        worker = Thread(target=run_pending, args=(application, stop), daemon=True)
        worker.start()
        Thread(target=run_delivery, args=(application, stop), daemon=True).start()
        print(f"六扇门  http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()


if __name__ == "__main__":
    main()
