"""Local desktop notifications and once-a-day Markdown briefings."""
import logging
from pathlib import Path
import re
import subprocess
import sys
from tempfile import NamedTemporaryFile

from .i18n import copy
from .inbox import build_inbox
from .rules import InputError
from .sources import CST, iso, now, web_url

LOGGER = logging.getLogger("liushanmen.delivery")
OSASCRIPT = Path("/usr/bin/osascript")
NOTIFICATION_SCRIPT = """on run argv
    display notification (item 2 of argv) with title (item 1 of argv)
end run
"""
TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


def desktop_available():
    return sys.platform == "darwin" and OSASCRIPT.is_file()


def desktop_notification(title, body):
    subprocess.run([str(OSASCRIPT), "-", title, body], input=NOTIFICATION_SCRIPT,
                   text=True, check=True, capture_output=True, timeout=8)


def markdown_text(value):
    text = " ".join(value.split()).replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_\[\]])", r"\\\1", text)


def render_briefing(inbox, lang):
    stories = inbox["stories"]
    priority = [story for story in stories if story["priority"] or story["focus"]]
    other = [story for story in stories if not story["priority"] and not story["focus"]]
    rows = [f'# {copy(lang, "六扇门 · 情报简报", "Liushanmen · Daily intelligence")} · {inbox["date"]}', "",
            copy(lang, f'{inbox["task_count"]} 个关注任务 · {len(stories)} 条进展 · {len(priority)} 条优先进展',
                 f'{inbox["task_count"]} tasks · {len(stories)} developments · {len(priority)} priorities')]

    for heading, group in ((copy(lang, "优先看", "Priorities"), priority),
                           (copy(lang, "其他进展", "Other developments"), other)):
        if not group:
            continue
        rows.extend(["", f"## {heading}", ""])
        for story in group[:12]:
            rows.append(f'- **{markdown_text(story["title"])}**')
            if story["summary"]:
                rows.append("  " + markdown_text(story["summary"]))
            for report in story["reports"][:3]:
                if url := web_url(report["url"]):
                    rows.append(f'  - [{markdown_text(report["source"])}](<{url}>)')
        if len(group) > 12:
            rows.append(copy(lang, f'另有 {len(group) - 12} 条可在收件箱查看。',
                             f'{len(group) - 12} more are available in the inbox.'))
    if not stories:
        rows.extend(["", copy(lang, "今天没有已保存的当日报道或事件更新。", "No reports or event updates were saved for today.")])
    if inbox["failures"]:
        rows.extend(["", f'## {copy(lang, "信源状态", "Source status")}', ""])
        for failure in inbox["failures"]:
            state = copy(lang, "已恢复", "Recovered") if failure["recovered_at"] else copy(lang, "读取失败", "Fetch failed")
            rows.append(f'- {markdown_text(failure["source"])} · {state} · {markdown_text(failure["note"])}')
    return "\n".join(rows) + "\n"


class Delivery:
    def __init__(self, database, catalog, notify=None):
        self.database = database
        self.catalog = catalog
        self.notify = notify if notify is not None else desktop_notification if desktop_available() else None
        parent = database.path.parent
        self.directory = parent / ("briefings" if database.path.stem == "liushanmen" else database.path.stem + "-briefings")

    def status(self):
        latest = self.database.latest_briefing()
        return {**self.database.delivery_settings(), "desktop_available": self.notify is not None,
                "latest_day": latest["day"] if latest else None, "last_error": self.database.last_delivery_error()}

    def save_settings(self, body, lang):
        alerting, daily, time = body.get("alerts"), body.get("daily"), body.get("time")
        if type(alerting) is not bool or type(daily) is not bool or not isinstance(time, str) or not TIME.fullmatch(time):
            raise InputError("请检查提醒开关与简报时间。")
        if alerting and self.notify is None:
            raise InputError("当前设备无法发送桌面提醒。")
        self.database.save_delivery_settings({"alerts": alerting, "daily": daily, "time": time, "locale": lang})
        return self.status()

    def test(self, lang):
        if self.notify is None:
            raise InputError("当前设备无法发送桌面提醒。")
        try:
            self.notify(copy(lang, "六扇门 · 测试提醒", "Liushanmen · Test notification"),
                        copy(lang, "桌面提醒已接通。", "The desktop notification channel is available."))
        except (OSError, subprocess.SubprocessError) as error:
            LOGGER.warning("Desktop notification test failed: %s", error)
            raise InputError("桌面提醒发送失败。") from error
        return {"sent": True}

    def tick(self, at=None):
        instant = at or now()
        local = instant.astimezone(CST)
        settings = self.database.delivery_settings()
        if settings["daily"] and local.strftime("%H:%M") >= settings["time"]:
            day = local.date().isoformat()
            latest = self.database.latest_briefing()
            if latest is None or latest["day"] < day:
                try:
                    self._save_briefing(day, instant, settings["locale"])
                except Exception:
                    LOGGER.exception("Could not create daily briefing")
        if self.notify is not None:
            for item in self.database.pending_delivery(iso(instant)):
                try:
                    self.notify(item["title"], item["body"])
                except (OSError, subprocess.SubprocessError) as error:
                    LOGGER.warning("Desktop notification failed: %s", error)
                    self.database.finish_delivery(item, instant, "desktop")
                else:
                    self.database.finish_delivery(item, instant)

    def _save_briefing(self, day, instant, lang):
        inbox = build_inbox(self.database, self.catalog, lang, at=instant)
        markdown = render_briefing(inbox, lang)
        filename = day + ".md"
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, delete=False)
        path = Path(temporary.name)
        try:
            with temporary:
                temporary.write(markdown)
            path.replace(self.directory / filename)
        finally:
            path.unlink(missing_ok=True)
        title = copy(lang, "六扇门 · 今日情报简报", "Liushanmen · Daily intelligence")
        count = len(inbox["stories"])
        top = "\n".join(story["title"][:68] for story in inbox["stories"][:2])
        body = copy(lang, f"{count} 条进展 · 简报已保存为 {filename}", f"{count} developments · Saved as {filename}")
        self.database.save_briefing(day, iso(instant), markdown, title, f"{body}\n{top}".strip(), announce=self.notify is not None)
