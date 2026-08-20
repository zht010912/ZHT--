from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Mapping


PENDING_VALUE = "待确认"


class GuardrailError(ValueError):
    """A deterministic input or model-output validation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class InjectionSpan:
    code: str
    start: int
    end: int


_INJECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "PROMPT_INJECTION_IGNORE_INSTRUCTIONS",
        re.compile(
            r"(?:请|务必|现在)?\s*(?:忽略|无视|覆盖|绕过|不要遵守)"
            r"\s*(?:以上|上述|之前|前面|先前|所有|系统|开发者|安全)?\s*(?:的)?"
            r"\s*(?:规则|指令|要求|提示(?:词)?|instructions?|rules?)",
            re.IGNORECASE,
        ),
    ),
    (
        "PROMPT_INJECTION_IGNORE_INSTRUCTIONS",
        re.compile(
            r"ignore\s+(?:all\s+)?(?:previous|prior|above|earlier|system)?\s*"
            r"(?:instructions?|rules?|prompts?)",
            re.IGNORECASE,
        ),
    ),
    (
        "PROMPT_INJECTION_SYSTEM_PROMPT",
        re.compile(
            r"(?:系统提示词|system\s+prompt|developer\s+(?:message|instruction))",
            re.IGNORECASE,
        ),
    ),
    (
        "PROMPT_INJECTION_ROLE_OVERRIDE",
        re.compile(
            r"(?:从现在开始|现在起|接下来)?\s*(?:你是|你要扮演|扮演)\s*[^，。；;\n]{1,40}",
            re.IGNORECASE,
        ),
    ),
    (
        "PROMPT_INJECTION_SECRET_REQUEST",
        re.compile(
            r"(?:泄露|展示|输出|打印|reveal|show|print).{0,20}"
            r"(?:密钥|密码|系统提示词|(?:[a-z][a-z0-9_]{0,30}_)?api[_\s-]*key|secret|system\s+prompt)",
            re.IGNORECASE,
        ),
    ),
)

_SENTENCE_BOUNDARIES = "。！？!?\n\r"
_AMBIGUOUS_VALUES = {
    "",
    PENDING_VALUE,
    "待定",
    "未定",
    "未明确",
    "不明确",
    "未知",
    "暂无",
    "无",
    "大家",
    "所有人",
    "团队",
    "项目组",
    "相关人员",
    "有关人员",
    "相关同事",
    "负责人",
    "unknown",
    "none",
    "null",
    "n/a",
}
_WEEKDAY_INDEX = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}
_TENTATIVE_UNASSIGNED_ACTION = re.compile(
    r"(?:也\s*可以|可以|可)\s*(?:再|进一步)?\s*(?:评估|考虑|讨论)"
    r"|(?:建议|提议)\s*(?:再|进一步)?\s*(?:评估|考虑|讨论)"
)


def validate_meeting_text(text: Any, max_chars: int) -> str:
    if not isinstance(text, str) or not text.strip():
        raise GuardrailError("INPUT_EMPTY", "会议记录不能为空。")
    if len(text) > max_chars:
        raise GuardrailError(
            "INPUT_TOO_LONG",
            f"会议记录超过允许的 {max_chars} 个字符。",
        )
    return text


def find_injection_spans(text: str) -> list[InjectionSpan]:
    """Return sentence-level spans containing recognizable prompt injection."""

    spans: list[InjectionSpan] = []
    seen: set[tuple[str, int, int]] = set()
    for code, pattern in _INJECTION_RULES:
        for match in pattern.finditer(text):
            start = match.start()
            while start > 0 and text[start - 1] not in _SENTENCE_BOUNDARIES:
                start -= 1
            end = match.end()
            while end < len(text) and text[end] not in _SENTENCE_BOUNDARIES:
                end += 1
            if end < len(text):
                end += 1
            item = (code, start, end)
            if item not in seen:
                seen.add(item)
                spans.append(InjectionSpan(code=code, start=start, end=end))
    return sorted(spans, key=lambda item: (item.start, item.end, item.code))


def detect_prompt_injection(text: str) -> list[str]:
    return list(dict.fromkeys(span.code for span in find_injection_spans(text)))


def parse_reference_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None

    candidate = value.strip()
    try:
        return date.fromisoformat(candidate[:10])
    except ValueError:
        pass

    match = re.search(
        r"(20\d{2})\s*[年/.\-]\s*(\d{1,2})\s*[月/.\-]\s*(\d{1,2})\s*日?",
        candidate,
    )
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def resolve_due_date(expression: Any, meeting_date: Any) -> str:
    """Resolve supported literal date expressions without trusting model calculations."""

    if not isinstance(expression, str) or expression.strip().casefold() in _AMBIGUOUS_VALUES:
        return PENDING_VALUE
    text = expression.strip()

    absolute = re.search(
        r"(20\d{2})\s*[年/.\-]\s*(\d{1,2})\s*[月/.\-]\s*(\d{1,2})\s*日?",
        text,
    )
    if absolute:
        try:
            return date(*(int(part) for part in absolute.groups())).isoformat()
        except ValueError:
            return PENDING_VALUE

    reference = parse_reference_date(meeting_date)
    if reference is None:
        return PENDING_VALUE

    month_day = re.search(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?", text)
    if month_day:
        try:
            resolved = date(reference.year, int(month_day.group(1)), int(month_day.group(2)))
        except ValueError:
            return PENDING_VALUE
        return resolved.isoformat() if resolved >= reference else PENDING_VALUE

    if re.search(r"(?:今天|今日)", text):
        return reference.isoformat()
    if re.search(r"(?:明天|次日|翌日)", text):
        return (reference + timedelta(days=1)).isoformat()
    if "后天" in text:
        return (reference + timedelta(days=2)).isoformat()

    days_later = re.search(r"(\d{1,3})\s*天后", text)
    if days_later:
        return (reference + timedelta(days=int(days_later.group(1)))).isoformat()

    week_day = re.search(
        r"(本周|这周|下周|下星期|下礼拜|下下周|下下星期|下下礼拜)\s*"
        r"(?:周|星期|礼拜)?([一二三四五六日天])",
        text,
    )
    if week_day:
        prefix, weekday_text = week_day.groups()
        week_offset = 0 if prefix in {"本周", "这周"} else 2 if prefix.startswith("下下") else 1
        monday = reference - timedelta(days=reference.weekday())
        resolved = monday + timedelta(weeks=week_offset, days=_WEEKDAY_INDEX[weekday_text])
        return resolved.isoformat()

    if "下月底" in text or "下月末" in text:
        next_month = date(reference.year + (reference.month == 12), reference.month % 12 + 1, 1)
        last_day = calendar.monthrange(next_month.year, next_month.month)[1]
        return date(next_month.year, next_month.month, last_day).isoformat()
    if re.search(r"(?:本月|这个月)?月底", text):
        last_day = calendar.monthrange(reference.year, reference.month)[1]
        return date(reference.year, reference.month, last_day).isoformat()

    return PENDING_VALUE


def postprocess_proposal(
    proposal: Mapping[str, Any],
    meeting_text: str,
    meeting_date: Any,
    *,
    enable_injection_guard: bool = True,
) -> tuple[dict[str, Any], list[str], list[str]]:
    if not isinstance(proposal, Mapping):
        raise GuardrailError("PROPOSAL_INVALID", "模型返回的 JSON 顶层必须是对象。")

    warnings: list[str] = []
    injection_spans = find_injection_spans(meeting_text) if enable_injection_guard else []
    security_flags = list(dict.fromkeys(span.code for span in injection_spans))
    if security_flags:
        warnings.append("检测到提示注入片段；该片段仅作为不可信会议内容处理。")

    summary = _clean_text(proposal.get("summary"))
    if enable_injection_guard and summary and detect_prompt_injection(summary):
        summary = ""
        warnings.append("摘要疑似包含注入指令，已移除并等待人工确认。")
    if not summary:
        summary = "未识别到有原文依据的会议摘要。"
        warnings.append("模型未提供可用摘要，已使用安全占位并等待人工确认。")

    decisions = _sanitize_decisions(
        proposal.get("decisions"), meeting_text, injection_spans, warnings
    )
    action_items = _sanitize_actions(
        proposal.get("action_items"),
        meeting_text,
        meeting_date,
        injection_spans,
        warnings,
    )

    return (
        {
            "summary": summary,
            "decisions": decisions,
            "action_items": action_items,
        },
        list(dict.fromkeys(warnings)),
        security_flags,
    )


def _sanitize_decisions(
    raw_decisions: Any,
    meeting_text: str,
    injection_spans: list[InjectionSpan],
    warnings: list[str],
) -> list[dict[str, str]]:
    if raw_decisions is None:
        return []
    if not isinstance(raw_decisions, list):
        warnings.append("决策列表格式无效，已忽略。")
        return []

    decisions: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_decisions:
        if not isinstance(item, Mapping):
            warnings.append("存在格式无效的决策项，已忽略。")
            continue
        decision = _clean_text(item.get("decision"))
        quote = _clean_text(item.get("source_quote"))
        grounded, safe, canonical_quote = _quote_status(quote, meeting_text, injection_spans)
        if not decision or not grounded:
            warnings.append("存在无法由原文引用支撑的决策，已忽略。")
            continue
        if not safe or detect_prompt_injection(decision):
            warnings.append("存在来源于提示注入片段的决策，已拒绝。")
            continue
        key = _dedup_key(decision)
        if key in seen:
            warnings.append("发现重复决策，已去重。")
            continue
        seen.add(key)
        decisions.append({"decision": decision, "source_quote": canonical_quote})
    return decisions


def _sanitize_actions(
    raw_actions: Any,
    meeting_text: str,
    meeting_date: Any,
    injection_spans: list[InjectionSpan],
    warnings: list[str],
) -> list[dict[str, Any]]:
    if raw_actions is None:
        return []
    if not isinstance(raw_actions, list):
        warnings.append("行动项列表格式无效，已忽略。")
        return []

    actions: list[dict[str, Any]] = []
    action_index: dict[str, int] = {}
    for item in raw_actions:
        if not isinstance(item, Mapping):
            warnings.append("存在格式无效的行动项，已忽略。")
            continue

        task = _clean_text(item.get("task"))
        quotes = _quote_list(item.get("source_quotes"))
        safe_quotes: list[str] = []
        for quote in quotes:
            grounded, safe, canonical_quote = _quote_status(quote, meeting_text, injection_spans)
            if grounded and safe and canonical_quote not in safe_quotes:
                safe_quotes.append(canonical_quote)
        if not task or not safe_quotes:
            warnings.append("存在无法由原文引用支撑的行动项，已忽略。")
            continue
        if detect_prompt_injection(task):
            warnings.append("存在疑似执行提示注入指令的行动项，已拒绝。")
            continue
        if len(safe_quotes) != len(quotes):
            warnings.append("行动项中的无效或注入来源引用已移除。")

        evidence = "\n".join(safe_quotes)
        owner_raw = _clean_text(item.get("owner"))
        owner = owner_raw if _is_specific(owner_raw) and owner_raw in evidence else PENDING_VALUE
        if owner == PENDING_VALUE and owner_raw != PENDING_VALUE:
            warnings.append("行动项负责人缺少明确原文依据，已标记待确认。")

        due_text_raw = _clean_text(item.get("due_date_text"))
        if not _is_specific(due_text_raw) or not _date_expression_is_grounded(due_text_raw, evidence):
            due_text = PENDING_VALUE
            due_date = PENDING_VALUE
            if due_text_raw != PENDING_VALUE:
                warnings.append("行动项截止日期缺少明确原文依据，已标记待确认。")
        else:
            due_text = due_text_raw
            due_date = resolve_due_date(due_text, meeting_date)
            if due_date == PENDING_VALUE:
                warnings.append("行动项截止日期无法确定解析，已标记待确认。")

        if (
            owner == PENDING_VALUE
            and due_date == PENDING_VALUE
            and _TENTATIVE_UNASSIGNED_ACTION.search(evidence)
        ):
            warnings.append("未指派且无期限的讨论性建议未转为行动项。")
            continue

        action = {
            "task": task,
            "owner": owner,
            "due_date_text": due_text,
            "due_date": due_date,
            "source_quotes": safe_quotes,
            "confidence": _confidence(item.get("confidence")),
        }

        key = _dedup_key(task)
        if key in action_index:
            _merge_duplicate_action(actions[action_index[key]], action, warnings)
            warnings.append("发现重复行动项，已合并去重。")
            continue
        action_index[key] = len(actions)
        actions.append(action)
    return actions


def _merge_duplicate_action(
    current: dict[str, Any],
    duplicate: dict[str, Any],
    warnings: list[str],
) -> None:
    current["source_quotes"] = list(
        dict.fromkeys([*current["source_quotes"], *duplicate["source_quotes"]])
    )
    current["confidence"] = max(current["confidence"], duplicate["confidence"])

    for text_key, resolved_key in (("owner", None), ("due_date_text", "due_date")):
        old_value = current[text_key]
        new_value = duplicate[text_key]
        if old_value == PENDING_VALUE and new_value != PENDING_VALUE:
            current[text_key] = new_value
            if resolved_key:
                current[resolved_key] = duplicate[resolved_key]
        elif old_value != PENDING_VALUE and new_value != PENDING_VALUE and old_value != new_value:
            current[text_key] = PENDING_VALUE
            if resolved_key:
                current[resolved_key] = PENDING_VALUE
            warnings.append("重复行动项的负责人或日期相互冲突，已标记待确认。")


def _quote_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _clean_text(item))]


def _quote_status(
    quote: str,
    meeting_text: str,
    injection_spans: list[InjectionSpan],
) -> tuple[bool, bool, str]:
    if not quote:
        return False, False, ""
    locations = [(match.start(), match.end()) for match in re.finditer(re.escape(quote), meeting_text)]
    if not locations:
        characters = [character for character in quote if not character.isspace()]
        if not characters:
            return False, False, ""
        whitespace_tolerant = r"\s*".join(re.escape(character) for character in characters)
        locations = [
            (match.start(), match.end())
            for match in re.finditer(whitespace_tolerant, meeting_text)
        ]
    if not locations:
        return False, False, ""
    for start, end in locations:
        if not any(start < span.end and end > span.start for span in injection_spans):
            return True, True, meeting_text[start:end]
    first_start, first_end = locations[0]
    return True, False, meeting_text[first_start:first_end]


def _is_specific(value: str) -> bool:
    return value.strip().casefold() not in _AMBIGUOUS_VALUES


def _date_expression_is_grounded(value: str, evidence: str) -> bool:
    """Allow harmless whitespace differences in a date token, not semantic rewrites."""

    compact_value = re.sub(r"\s+", "", value)
    compact_evidence = re.sub(r"\s+", "", evidence)
    return bool(compact_value) and compact_value in compact_evidence


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _dedup_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(min(1.0, max(0.0, number)), 4)
