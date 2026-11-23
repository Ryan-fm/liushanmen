"""SQLite storage for plans, source records, versioned events and run results."""
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta
from functools import partial
import json
import sqlite3
from uuid import uuid4

from .i18n import copy
from .rules import InputError
from .sources import date, iso, now

DEFAULT_DELIVERY = {"alerts": False, "daily": False, "time": "20:00", "locale": "zh-CN"}


def pack(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Database:
    def __init__(self, path):
        self.path = path
        with self.connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, plan TEXT NOT NULL, intent TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0, demo INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, next_at TEXT, revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    id TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY (task_id, id)
                );
                CREATE TABLE IF NOT EXISTS task_memory (
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    id TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, id)
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    mode TEXT NOT NULL, created_at TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runs_task ON runs(task_id, created_at);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    topic TEXT NOT NULL, status TEXT NOT NULL,
                    updated_at TEXT NOT NULL, data TEXT NOT NULL, history TEXT NOT NULL,
                    UNIQUE (task_id, topic)
                );
                CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notification_outbox (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                    created_at TEXT NOT NULL, next_at TEXT NOT NULL, sent_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS daily_briefings (
                    day TEXT PRIMARY KEY, created_at TEXT NOT NULL, markdown TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def task_row(row):
        if row is None:
            raise InputError("找不到任务")
        return {**dict(row), "plan": json.loads(row["plan"]), "active": bool(row["active"]), "demo": bool(row["demo"])}

    def create(self, plan, intent, demo=False, *, connection=None):
        key = uuid4().hex[:12]
        arguments = (key, pack(plan), intent, int(demo), iso(now()))
        statement = "INSERT INTO tasks(id, plan, intent, demo, created_at) VALUES(?,?,?,?,?)"
        if connection is not None:
            connection.execute(statement, arguments)
        else:
            with self.connect() as conn:
                conn.execute(statement, arguments)
        return key

    def task(self, key):
        with self.connect() as connection:
            return self.task_row(connection.execute("SELECT * FROM tasks WHERE id=?", (key,)).fetchone())

    def index(self):
        with self.connect() as connection:
            data = connection.execute("""
                SELECT t.*, (SELECT COUNT(*) FROM evidence s WHERE s.task_id=t.id) evidence_count,
                       (SELECT COUNT(*) FROM events e WHERE e.task_id=t.id AND e.status!='resolved') event_count
                FROM tasks t ORDER BY t.demo, t.created_at DESC, t.rowid DESC
            """).fetchall()
        return [self.task_row(row) for row in data]

    def update_plan(self, key, plan, *, revision=None):
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET plan=?,revision=revision+1 WHERE id=? AND (? IS NULL OR revision=?)",
                (pack(plan), key, revision, revision),
            )
            if cursor.rowcount != 1:
                if revision is not None and connection.execute("SELECT 1 FROM tasks WHERE id=?", (key,)).fetchone():
                    raise InputError("规则已更新，请重新生成记忆草案。")
                raise InputError("找不到任务")

    def insights(self, key):
        self.task(key)
        with self.connect() as connection:
            counts = Counter(json.loads(row["data"])["source"] for row in connection.execute(
                "SELECT data FROM evidence WHERE task_id=?", (key,)
            ))
            rows = connection.execute(
                "SELECT id, created_at, result FROM runs WHERE task_id=? AND mode='live' "
                "ORDER BY created_at DESC,rowid DESC LIMIT 10", (key,)
            ).fetchall()
        return {
            "evidence_count": sum(counts.values()),
            "sources": [{"name": name, "count": count} for name, count in
                        sorted(counts.items(), key=lambda entry: (-entry[1], entry[0].casefold()))[:5]],
            "checks": [{"id": row["id"], "at": row["created_at"], "count": json.loads(row["result"])["total"]}
                       for row in reversed(rows)],
        }

    def memories(self, key):
        self.task(key)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id,text,created_at,updated_at FROM task_memory WHERE task_id=? ORDER BY created_at DESC,rowid DESC",
                (key,)
            ).fetchall()
        return [dict(row) for row in rows]

    def tasks_with_memories(self):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT t.id,t.plan,t.intent,m.text FROM tasks t JOIN task_memory m ON m.task_id=t.id "
                "WHERE t.demo=0 ORDER BY m.updated_at DESC,m.rowid DESC"
            ).fetchall()
        tasks = {}
        for row in rows:
            if row["id"] not in tasks:
                tasks[row["id"]] = {"plan": json.loads(row["plan"]), "intent": row["intent"], "notes": []}
            tasks[row["id"]]["notes"].append({"text": row["text"]})
        return tasks.values()

    def memory(self, key, note_id):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id,text,created_at,updated_at FROM task_memory WHERE task_id=? AND id=?", (key, note_id)
            ).fetchone()
        if row is None:
            raise InputError("找不到这条记忆。")
        return dict(row)

    def add_memory(self, key, text):
        self.task(key)
        note_id, stamp = uuid4().hex[:12], iso(now())
        with self.connect() as connection:
            connection.execute("INSERT INTO task_memory VALUES(?,?,?,?,?)", (key, note_id, text, stamp, stamp))
        return {"id": note_id, "text": text, "created_at": stamp, "updated_at": stamp}

    def update_memory(self, key, note_id, text):
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE task_memory SET text=?,updated_at=? WHERE task_id=? AND id=?", (text, iso(now()), key, note_id)
            )
            if cursor.rowcount != 1:
                raise InputError("找不到这条记忆。")
            return dict(connection.execute(
                "SELECT id,text,created_at,updated_at FROM task_memory WHERE task_id=? AND id=?", (key, note_id)
            ).fetchone())

    def remove_memory(self, key, note_id):
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM task_memory WHERE task_id=? AND id=?", (key, note_id))
            if cursor.rowcount != 1:
                raise InputError("找不到这条记忆。")

    def set_active(self, key, active):
        with self.connect() as connection:
            cursor = connection.execute("UPDATE tasks SET active=?,next_at=? WHERE id=?",
                                        (int(active), iso(now()) if active else None, key))
            if cursor.rowcount != 1:
                raise InputError("找不到任务")

    def due(self, instant):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM tasks WHERE active=1 AND next_at<=? ORDER BY next_at LIMIT 12", (instant,)
            ).fetchall()
        return [row["id"] for row in rows]

    def postpone(self, key, instant):
        with self.connect() as connection:
            connection.execute("UPDATE tasks SET next_at=? WHERE id=? AND active=1", (instant, key))

    def ingest(self, key, evidence, *, connection=None):
        def write(conn):
            total = conn.total_changes
            conn.executemany("INSERT OR IGNORE INTO evidence VALUES(?,?,?)",
                             ((key, item["id"], pack(item)) for item in evidence))
            return conn.total_changes - total
        if connection is not None:
            return write(connection)
        with self.connect() as conn:
            return write(conn)

    def records(self, key):
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM evidence WHERE task_id=?", (key,)).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def inbox_snapshot(self, start, end):
        with self.connect() as connection:
            connection.execute("BEGIN")
            tasks = {row["id"]: {**self.task_row(row), "records": [], "notes": [], "events": [], "checks": []}
                     for row in connection.execute("SELECT * FROM tasks WHERE demo=0")}
            if not tasks:
                return []
            for row in connection.execute(
                "SELECT e.task_id,e.data FROM evidence e JOIN tasks t ON t.id=e.task_id WHERE t.demo=0"
            ):
                record = json.loads(row["data"])
                if start <= date(record["published_at"]) <= end:
                    tasks[row["task_id"]]["records"].append(record)
            for row in connection.execute(
                "SELECT m.task_id,m.text FROM task_memory m JOIN tasks t ON t.id=m.task_id WHERE t.demo=0 "
                "ORDER BY m.updated_at DESC,m.rowid DESC"
            ):
                tasks[row["task_id"]]["notes"].append({"text": row["text"]})
            for row in connection.execute(
                "SELECT e.* FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.demo=0 AND e.updated_at BETWEEN ? AND ?",
                (iso(start), iso(end))
            ):
                tasks[row["task_id"]]["events"].append(self.event_row(row))
            for row in connection.execute(
                "SELECT r.task_id,r.id,r.created_at,r.result FROM runs r JOIN tasks t ON t.id=r.task_id "
                "WHERE t.demo=0 AND r.mode='live' AND r.created_at BETWEEN ? AND ? ORDER BY r.created_at,r.rowid",
                (iso(start), iso(end))
            ):
                tasks[row["task_id"]]["checks"].append({
                    "id": row["id"], "at": row["created_at"], "sources": json.loads(row["result"]).get("sources", []),
                })
        return list(tasks.values())

    @staticmethod
    def event_row(row):
        data = json.loads(row["data"])
        return {**data, "id": row["id"], "status": row["status"], "updated_at": row["updated_at"],
                "history": json.loads(row["history"])}

    def detail(self, key):
        with self.connect() as connection:
            task = self.task_row(connection.execute("SELECT * FROM tasks WHERE id=?", (key,)).fetchone())
            event_rows = connection.execute(
                "SELECT * FROM events WHERE task_id=? ORDER BY status='resolved', updated_at DESC", (key,)
            ).fetchall()
            run_rows = connection.execute(
                "SELECT * FROM runs WHERE task_id=? ORDER BY created_at DESC,rowid DESC LIMIT 15", (key,)
            ).fetchall()
        return {
            **task, "events": [self.event_row(row) for row in event_rows],
            "runs": [{**dict(row), "result": json.loads(row["result"])} for row in run_rows],
        }

    def status(self, task_id, event_id, status, note):
        stamp = iso(now())
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM events WHERE task_id=? AND id=?", (task_id, event_id)).fetchone()
            if not row:
                raise InputError("找不到该事件")
            history = json.loads(row["history"])
            history.append({"at": stamp, "type": status, "text": note})
            connection.execute("UPDATE events SET status=?,updated_at=?,history=? WHERE id=?",
                               (status, stamp, pack(history[-60:]), event_id))

    @staticmethod
    def _delivery_settings(connection):
        row = connection.execute("SELECT value FROM meta WHERE name='delivery'").fetchone()
        return {**DEFAULT_DELIVERY, **(json.loads(row["value"]) if row else {})}

    def delivery_settings(self):
        with self.connect() as connection:
            return self._delivery_settings(connection)

    def save_delivery_settings(self, settings):
        with self.connect() as connection:
            connection.execute("INSERT OR REPLACE INTO meta VALUES('delivery',?)", (pack(settings),))
            for setting, kind in (("alerts", "change"), ("daily", "briefing")):
                if not settings[setting]:
                    connection.execute("DELETE FROM notification_outbox WHERE kind=? AND sent_at IS NULL", (kind,))

    @staticmethod
    def _queue_delivery(connection, key, kind, title, body, stamp):
        connection.execute("INSERT OR IGNORE INTO notification_outbox(id,kind,title,body,created_at,next_at) VALUES(?,?,?,?,?,?)",
                           (key, kind, title, body, stamp, stamp))

    def pending_delivery(self, stamp):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM notification_outbox WHERE sent_at IS NULL AND next_at<=? ORDER BY created_at LIMIT 6", (stamp,)
            ).fetchall()
        return [dict(row) for row in rows]

    def finish_delivery(self, item, at, error=None):
        with self.connect() as connection:
            if error is None:
                connection.execute("UPDATE notification_outbox SET sent_at=?,last_error=NULL WHERE id=?", (iso(at), item["id"]))
            else:
                delay = min(60, 2 ** min(item["attempts"] + 1, 6))
                connection.execute("UPDATE notification_outbox SET attempts=attempts+1,next_at=?,last_error=? WHERE id=?",
                                   (iso(at + timedelta(minutes=delay)), error, item["id"]))

    def latest_briefing(self):
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM daily_briefings ORDER BY day DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def save_briefing(self, day, stamp, markdown, title, body, *, announce):
        with self.connect() as connection:
            cursor = connection.execute("INSERT OR IGNORE INTO daily_briefings VALUES(?,?,?)", (day, stamp, markdown))
            if cursor.rowcount and announce and self._delivery_settings(connection)["daily"]:
                self._queue_delivery(connection, "briefing:" + day, "briefing", title, body, stamp)

    def last_delivery_error(self):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT last_error FROM notification_outbox WHERE sent_at IS NULL AND last_error IS NOT NULL "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return row["last_error"] if row else None

    def save_run(self, task, mode, stamp, result, candidates, next_at=None):
        run_id = uuid4().hex[:12]
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT revision,active FROM tasks WHERE id=?", (task["id"],)).fetchone()
            if current["revision"] != task["revision"]:
                raise InputError("规则已更新，请按新规则重新运行")
            if mode == "live" and not current["active"]:
                raise InputError("任务已暂停，本次未更新事件")
            if mode == "live":
                changes = self.update_events(connection, task, stamp, candidates, set(result["complete"]))
                if changes and not task["demo"]:
                    settings = self._delivery_settings(connection)
                    if settings["alerts"]:
                        lang = settings["locale"]
                        labels = copy(lang, "、", ", ").join(changes[:3])
                        text = copy(lang, f"{len(changes)} 个事件有重要变化 · {labels}",
                                    f"Important changes in {len(changes)} events · {labels}")
                        self._queue_delivery(connection, "change:" + run_id, "change",
                                             copy(lang, "六扇门 · 重要变化", "Liushanmen · Important update"),
                                             f"{task['plan']['title']}\n{text}", stamp)
                connection.execute("UPDATE tasks SET next_at=? WHERE id=?", (next_at, task["id"]))
            connection.execute("INSERT INTO runs VALUES(?,?,?,?,?)",
                               (run_id, task["id"], mode, stamp, pack(result)))
        return run_id

    def update_events(self, connection, task, stamp, candidates, complete):
        text = partial(copy, task["plan"].get("locale"))
        changes = []
        prior = {
            row["topic"]: row for row in connection.execute("SELECT * FROM events WHERE task_id=?", (task["id"],))
        }
        for candidate in candidates:
            label = candidate["label"]
            row = prior.get(label)
            stage = candidate["stage"]
            if not row:
                if stage != "alert":
                    continue
                data = {**candidate, "total_ids": candidate["window_ids"]}
                history = [{"at": stamp, "type": "new", "text": text("达到触发条件，开始核查。", "The rule triggered. Review is pending.")}]
                connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                                   (uuid4().hex[:12], task["id"], label, "open", stamp, pack(data), pack(history)))
                changes.append(label)
                continue
            if label not in complete:
                continue
            old = json.loads(row["data"])
            known = set(old.get("total_ids", []))
            new_ids = set(candidate["window_ids"]) - known
            if row["status"] == "resolved" and (not new_ids or stage != "alert"):
                continue
            if not new_ids and old.get("stage") == stage and old.get("window_ids") == candidate["window_ids"]:
                continue
            status = "open" if row["status"] == "resolved" else row["status"]
            history = json.loads(row["history"])
            parts = []
            if new_ids:
                parts.append(text(f"发现 {len(new_ids)} 条新增独立证据。", f"New independent records — {len(new_ids)}."))
            if old.get("stage") != stage:
                parts.append(text("达到触发条件。", "The rule triggered.") if stage == "alert" else
                             text("当前时间窗已低于触发条件，等待复核。", "The window is below the threshold and needs another check."))
            if not parts:
                parts.append(text("观察窗口已变化。", "The lookback window changed."))
            if row["status"] == "resolved":
                parts.insert(0, text("新证据达到阈值，事件重新开启。", "New evidence met the threshold and reopened the event."))
            history.append({"at": stamp, "type": "update", "text": text("", " ").join(parts)})
            if new_ids or candidate["evidence"]:
                data = {**candidate, "total_ids": sorted(known | new_ids)}
            else:
                data = {**candidate, "total_ids": sorted(known), "evidence": old.get("evidence", []),
                        "evidence_archived": True}
            connection.execute("UPDATE events SET status=?,updated_at=?,data=?,history=? WHERE id=?",
                               (status, stamp, pack(data), pack(history[-60:]), row["id"]))
            if stage == "alert" and (new_ids or old.get("stage") != "alert"):
                changes.append(label)
        return changes
