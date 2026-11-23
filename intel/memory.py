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
FOCUS_ALIASES = (
    ("安全车", "Safety car", ("安全车", "safety car", "safety cars")),
    ("车手变动", "Driver changes", (
        "车手变动", "车手更换", "车手变更", "车手变动情况", "车手阵容", "车手转会", "车手席位",
        "driver change", "driver changes", "driver lineup", "driver line up", "driver swap", "driver swaps",
        "driver transfer", "driver moves", "driver signing", "driver roster", "driver replacement",
        "will drive for", "to drive for",
    )),
)


def terms_from_memory(text):
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


def rank_by_memory(records, focus):
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
        item = {**record, "memory_hits": matched} if matched else record
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
