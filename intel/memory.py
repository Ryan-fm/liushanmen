"""Turn a saved, task-local idea into a reviewable rule draft."""
import re

from .i18n import copy
from .rules import InputError, validate

KEYWORDS = re.compile(r"(?:关键词|关注|重点盯|keywords?|focus(?: on)?)\s*[:：]\s*([^。；;\n]+)", re.I)
QUOTED = re.compile(r'["「『“《]([^"」』”》]+)["」』”》]')
INTRO = re.compile(
    r"^(?:(?:请|我想|希望|下次|接下来|重点|多留意|关注|留意|跟踪|了解|看看)\s*|"
    r"(?:please|i want to|next time,?|especially|prioritize|focus on|track|monitor|watch for)\s+)+", re.I
)
SEPARATORS = re.compile(r"[,，、；;。！？!?\n]|以及|\s+and\s+", re.I)


def terms_from_memory(text):
    if match := KEYWORDS.search(text):
        phrases = SEPARATORS.split(match[1])
    else:
        phrases = QUOTED.findall(text)
        if not phrases:
            phrases = SEPARATORS.split(INTRO.sub("", text))
    cleaned = [phrase.strip(" \t.:：'’“”\"「」")[:80] for phrase in phrases]
    return list(dict.fromkeys(term for term in cleaned if len(term) >= 2))[:8]


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
