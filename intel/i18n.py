"""Language identifiers and bilingual system messages."""
import re


def locale(value):
    if isinstance(value, str) and value.partition(",")[0].partition(";")[0].strip().lower().split("-")[0] == "en":
        return "en"
    return "zh-CN"


def copy(lang, chinese, english):
    return english if lang == "en" else chinese


ERRORS = {
    "请补充关注对象或希望解决的问题": "Describe what you want to track or the problem you want to investigate.",
    "请选择启用或暂停": "Choose whether to enable or pause this task.",
    "每次导入 1 至 3000 条记录": "Import between 1 and 3,000 records at a time.",
    "来源类型不正确": "Invalid source type.",
    "事件状态不正确": "Invalid event status.",
    "仅允许访问本地工作台": "This workspace is available over localhost only.",
    "找不到页面": "Page not found.",
    "找不到请求的资源": "Resource not found.",
    "请求须为 JSON": "The request must use JSON.",
    "请求体为空或超过 8 MB": "The request is empty or exceeds 8 MB.",
    "请求 JSON 须为对象": "The JSON request must be an object.",
    "处理失败，请在本地服务日志查看详情": "The request failed. See the local service log.",
    "检索中断，请重试": "The search was interrupted. Try again.",
    "该任务已在运行": "This task is already running.",
    "运行模式须为试跑或正式运行": "Choose a trial run or a live check.",
    "启用方案后可运行正式监测": "Enable the task before running a live check.",
    "试跑结束时间不能在未来": "A trial run cannot end in the future.",
    "找不到任务": "Task not found.",
    "找不到该事件": "Event not found.",
    "规则已更新，请按新规则重新运行": "The rules changed during the run. Run again using the updated rules.",
    "任务已暂停，本次未更新事件": "The task was paused. Its events were left as they were.",
    "请先查看一轮新闻预览": "Preview the news before enabling monitoring.",
    "新闻预览已过期，请重新查询后确认": "This preview expired. Search again before enabling monitoring.",
    "请至少选择一个数据来源或填写公开新闻搜索词": "Select a source or enter a public news query.",
    "方案须为结构化对象": "The plan must be a structured object.",
    "请配置 1 至 12 个研判主题": "Add between 1 and 12 topics.",
    "主题格式不正确": "Invalid topic format.",
    "方案包含未配置的 RSS 数据源": "The plan contains an RSS source that is unavailable.",
    "每条证据须为对象": "Each evidence record must be an object.",
    "证据必须有时间；请使用 ISO 8601 或 YYYY-MM-DD HH:MM": "Every record needs a timestamp in ISO 8601 or YYYY-MM-DD HH:MM.",
    "证据链接只接受 HTTP 或 HTTPS": "Evidence links must use HTTP or HTTPS.",
    "kind 只接受 internal、public 或 media": "The kind field must be internal, public, or media.",
}
FIELDS = {
    "监测需求": "Monitoring request", "原始需求": "Original request", "来源名称": "Source name",
    "处理备注": "Progress note", "主题名称": "Topic name", "关键词": "Keywords",
    "建议负责人": "Suggested owner", "核查动作": "Review action", "RSS 数据源": "RSS sources",
    "任务名称": "Task name", "任务目标": "Goal", "关注对象": "Tracked entities",
    "触发条数": "Record threshold", "交叉来源数": "Required independent sources",
    "回看小时数": "Lookback hours", "检查间隔（分钟）": "Check interval",
    "公开新闻搜索词": "Public news query", "证据原文": "Evidence text",
    "证据标题": "Evidence title", "来源": "Source", "证据链接": "Evidence link", "外部编号": "External ID",
    "证据对象": "Tracked entity", "订单或工单编号": "Reference number",
}
FIELD_ERRORS = (
    (r"(.+)必须是文本", "{0} must be text."),
    (r"(.+)长度不符合要求（上限 (\d+) 字）", "{0} needs a valid length (maximum {1} characters)."),
    (r"(.+)须为 (\d+) 至 (\d+) 的整数", "{0} must be an integer from {1} to {2}."),
    (r"(.+)最多 (\d+) 项", "{0} allows up to {1} entries."),
)


def error_text(message, lang):
    if lang != "en":
        return message
    if message in ERRORS:
        return ERRORS[message]
    for pattern, template in FIELD_ERRORS:
        if match := re.fullmatch(pattern, message):
            field, *numbers = match.groups()
            return template.format(FIELDS.get(field, field), *numbers)
    if match := re.fullmatch(r"第 (\d+) 条：(.+)", message):
        return f"Record {match[1]} — {error_text(match[2], lang)}"
    if message.startswith("无法识别时间："):
        return "Unrecognized timestamp — " + message.partition("：")[2]
    if message.startswith("主题重复："):
        return "Duplicate topic — " + message.partition("：")[2]
    if match := re.fullmatch(r"(.+) 至少需要一项关键词", message):
        return f"Add at least one keyword for {match[1]}."
    return message
