"""Draft rules and rank collected records using task-local memory."""
import re
from unicodedata import normalize

from .i18n import copy
from .rules import InputError, validate

KEYWORDS = re.compile(r"(?:关键词|关注|重点盯|keywords?|focus(?: on)?)\s*[:：]\s*([^。；;\n]+)", re.I)
QUOTED = re.compile(r'["「『“《]([^"」』”》]+)["」』”》]')
INTRO = re.compile(
    r"^(?:(?:请|我想|希望|下次|接下来|重点|多留意|关注|留意|跟踪|了解|看看)\s*|"
    r"(?:please|i want to|next time,?|especially|prioritize|focus on|track|monitor|watch for)\s+)+", re.I
)
SEPARATORS = re.compile(r"[,，、；;。！？!?\n]|以及|\s+and\s+", re.I)
EXCLUSION = re.compile(r"无需|不用|不再|不要|忽略|排除|\b(?:ignore|exclude|skip|do not|don't)\b", re.I)
SEPARATOR_SPACE = re.compile(r"[\s\-‐‑‒–—]+")
NICKNAME_PREFIX = "称呼："
SELF_NAME = re.compile(
    r"^(?:我叫\s*|我的(?:名字|称呼)是\s*|以后叫我\s*|my name is\s+|call me\s+)([^\n]{1,60})$", re.I,
)
REMEMBER_VERB = r"(?:记下来|记一下|记下|记住|保存到(?:任务)?记忆)"
REMEMBER_START = re.compile(r"^(?:(?:请|你|帮我|麻烦你)\s*)*" + REMEMBER_VERB + r"\s*[:：,，]?\s*", re.I)
REMEMBER_END = re.compile(r"(?:[\s,，。；;]+(?:(?:请|你|帮我)\s*)?" + REMEMBER_VERB +
                          r"|[,，]\s*remember (?:that|it))$", re.I)
REMEMBER_EN = re.compile(r"^(?:please\s+)?remember(?:\s+that\b|\b)\s*[:：]?\s*", re.I)
REMEMBER_POINTER = re.compile(r"^(?:这个|这条|这件事|刚才那句|上面这句|我的(?:名字|称呼)|it|that|this|my name)?[吧呀啊哈哦]?$", re.I)
MEMORY_SCOPE = re.compile(r"^(全局记忆|任务记忆|workspace memory|task memory)\s*[:：]\s*", re.I)
FOCUS_ALIASES = (
    ("安全车", "Safety car", ("安全车", "safety car", "safety cars")),
    ("车手变动", "Driver changes", (
        "车手变动", "车手更换", "车手变更", "车手变动情况", "车手阵容", "车手转会", "车手席位",
        "driver change", "driver changes", "driver lineup", "driver line up", "driver swap", "driver swaps",
        "driver transfer", "driver moves", "driver signing", "driver roster", "driver replacement",
        "will drive for", "to drive for",
    )),
)


def memory_nickname(text):
    return text.removeprefix(NICKNAME_PREFIX).strip() if text.startswith(NICKNAME_PREFIX) else ""


def explicit_nickname(text):
    match = SELF_NAME.fullmatch(text.strip(" \t。！!"))
    name = match[1].strip(" \t\"'“”‘’「」") if match else ""
    return "" if name in {"什么", "什么名字", "啥", "啥名字"} or re.search(r"[?？。！!]", name) else name


def remember_request(question):
    """Return a requested note, an empty reference to prior context, or None."""
    text = question.strip()
    if text.endswith(("?", "？")) or re.match(r"^(?:请\s*)?(?:别|不要|不用|记住了|do not\b|don't\b)", text, re.I):
        return None
    text = text.rstrip("。！!.")
    if match := REMEMBER_END.search(text):
        text = text[:match.start()]
    elif match := REMEMBER_START.match(text) or REMEMBER_EN.match(text):
        text = text[match.end():]
    elif text.startswith("以后叫我") and (name := explicit_nickname(text)):
        return NICKNAME_PREFIX + name
    elif MEMORY_SCOPE.match(text):
        return text
    else:
        return None
    text = text.strip(" \t，,。;；")
    if REMEMBER_POINTER.fullmatch(text):
        return ""
    name = explicit_nickname(text)
    return NICKNAME_PREFIX + name if name else text


def scoped_chat_memory(text):
    explicit = MEMORY_SCOPE.match(text)
    content = text[explicit.end():].strip() if explicit else text
    if name := explicit_nickname(content):
        content = NICKNAME_PREFIX + name
    if memory_nickname(content):
        return "workspace", content
    task_scope = explicit[1].casefold() in {"任务记忆", "task memory"} if explicit else bool(KEYWORDS.match(content))
    return ("task" if task_scope else "workspace"), content


def terms_from_memory(text):
    if memory_nickname(text):
        return []
    if match := KEYWORDS.search(text):
        phrases = SEPARATORS.split(match[1])
    else:
        phrases = QUOTED.findall(text)
        if not phrases:
            phrases = SEPARATORS.split(INTRO.sub("", text))
    cleaned = [phrase.strip(" \t.:：'’“”\"「」")[:80] for phrase in phrases]
    return list(dict.fromkeys(term for term in cleaned if len(term) >= 2))[:8]


def searchable_text(value):
    return SEPARATOR_SPACE.sub(" ", normalize("NFKC", value).casefold()).strip()


def phrase_pattern(phrase):
    phrase = searchable_text(phrase)
    # English aliases match whole words, while Chinese terms can appear within sentences.
    left = r"(?<![a-z0-9])" if re.match(r"[a-z0-9]", phrase) else ""
    right = r"(?![a-z0-9])" if re.search(r"[a-z0-9]$", phrase) else ""
    return re.compile(left + re.escape(phrase) + right)


def focus_from_memory(notes, lang):
    alias_groups = [(copy(lang, zh, en), aliases,
                     [phrase_pattern(alias) for alias in aliases]) for zh, en, aliases in FOCUS_ALIASES]
    labels = {}
    for note in notes:
        if EXCLUSION.search(note["text"]) and not KEYWORDS.match(note["text"]):
            continue
        for term in terms_from_memory(note["text"]):
            text = searchable_text(term)
            if not text or EXCLUSION.search(term):
                continue
            equivalents = [(label, aliases) for label, aliases, patterns in alias_groups
                           if any(pattern.search(text) for pattern in patterns)]
            for label, aliases in equivalents or [(term, (term,))]:
                labels.setdefault(label.casefold(), (label, aliases))
    return {label: tuple(phrase_pattern(alias) for alias in aliases) for label, aliases in labels.values()}


def rank_by_focus(records, focus, *, match_key="memory_hits"):
    if not focus:
        return records
    ranked = []
    for record in records:
        title = searchable_text(record["title"])
        content = searchable_text(" ".join(record.get(key, "") for key in ("summary", "text", "entity")))
        title_hits = 0
        matched = []
        for label, patterns in focus.items():
            if any(pattern.search(title) for pattern in patterns):
                title_hits += 1
                matched.append(label)
            elif any(pattern.search(content) for pattern in patterns):
                matched.append(label)
        item = {**record, match_key: matched} if matched else record
        ranked.append((title_hits, len(matched), item))
    ranked.sort(key=lambda item: item[:2], reverse=True)
    return [item for _, _, item in ranked]


def draft_from_memory(plan, text, feeds):
    terms = terms_from_memory(text)
    if not terms:
        raise InputError("这条记忆没有可用的关注词。可以写成「关注：安全车、车手变动」。")
    lang = plan.get("locale", "zh-CN")
    label = copy(lang, "记忆关注", "Memory focus")
    topics = list(plan["topics"])
    for index, topic in enumerate(topics):
        if topic["label"].casefold() == label.casefold():
            combined = {term.casefold(): term for term in terms}
            combined.update({term.casefold(): term for term in topic["terms"]})
            topics[index] = {**topic, "terms": list(combined.values())}
            break
    else:
        topics.append({
            "label": label, "terms": terms,
            "owner": copy(lang, "待分派", "Unassigned"),
            "action": copy(lang, "复核命中记录是否符合这条关注点。", "Check whether matching records address this area of interest."),
        })
    return validate({**plan, "topics": topics}, feeds)
