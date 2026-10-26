"""Suggested public playbooks when a goal has no creator-written plan.

These are templates derived from the success definition and domain. They are not
claims that the creator did the steps, and they do not include evidence or odds.
"""

from __future__ import annotations

import ast
import json
from typing import Any

_MAX_ITEMS = 8


def normalize_steps(value: Any) -> list[str]:
    """Turn a strategy or milestone value into separate public lines.

    `str(some_list)` used to be stored as one string. Parse that back into items.
    """
    if value is None:
        return []
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            if isinstance(item, str):
                lines.extend(normalize_steps(item) if _looks_like_list(item) else _line(item))
            elif isinstance(item, dict):
                text = item.get("text") or item.get("step") or item.get("title") or item.get("name")
                detail = item.get("detail") or item.get("description")
                if isinstance(text, str) and text.strip():
                    step = text.strip()
                    if isinstance(detail, str) and detail.strip() and detail.strip() not in step:
                        step = f"{step}: {detail.strip()}"
                    lines.append(step[:500])
            else:
                lines.extend(normalize_steps(str(item)))
        return _unique(lines)
    if isinstance(value, dict):
        return normalize_steps([value])
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if _looks_like_list(text):
            parsed = _parse_list(text)
            if parsed is not None:
                return normalize_steps(parsed)
        if "\n" in text:
            return _unique([item.strip(" -•\t") for item in text.splitlines() if item.strip()])
        return [text[:500]]
    return []


def suggest_playbook(
    *,
    title: str,
    success: dict[str, Any],
    category: str,
    goal_type: str,
) -> tuple[list[str], list[str], list[str]]:
    """Steps, milestones, and evidence to log. No observed results."""
    blob = " ".join(
        str(part or "")
        for part in (
            title,
            success.get("metric"),
            success.get("unit"),
            success.get("event"),
            category,
            goal_type,
        )
    ).lower()
    unit = str(success.get("unit") or "").strip()
    if any(token in blob for token in ("book", "reading")):
        return _reading(success)
    if _is_money(blob, unit):
        return _savings(success, unit)
    if any(token in blob for token in ("10k", "marathon", "5k", "run a", "workout", "fitness")):
        return _fitness(title)
    if any(token in blob for token in ("dinner", "host")):
        return _dinners(success)
    if _is_hiring(blob, category):
        return _hiring()
    return _generic(title, success)


def _hiring() -> tuple[list[str], list[str], list[str]]:
    return (
        [
            "Send targeted applications only to roles that match the offer you want, "
            "and log each submission.",
            "Cold email engineers or founders about a specific role. A cold email is not "
            "an application; log sends and replies separately.",
            "Ask for warm introductions and keep a short list of conversations "
            "that started from them.",
            "Practice the interview format you are weakest at, and write down "
            "what failed after each round.",
            "Prepare one project you can walk through in a final loop, and note "
            "which interviews used it.",
        ],
        [
            "First targeted applications logged, separate from outreach",
            "First reply or warm introduction from outreach",
            "First technical interview",
            "First final-round interview",
            "Signed offer",
        ],
        [
            "Applications submitted",
            "Outreach emails sent",
            "Replies to outreach",
            "Interviews completed",
            "Offer received",
        ],
    )


def _reading(success: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    amount = _target_amount(success)
    total = int(amount) if amount and amount > 0 else 24
    marks = []
    for fraction in (0.25, 0.5, 0.75, 1):
        count = max(1, round(total * fraction))
        if count not in marks:
            marks.append(count)
    return (
        [
            "Decide what counts as a finished book before you start, including abandoned books.",
            "Pick a weekly finish rate you can keep until the deadline, and protect that time.",
            "Log each book on the day you finish it, with the title.",
            "If you fall behind, choose a shorter next book instead of skipping the log.",
        ],
        [f"{count} books finished" for count in marks],
        ["Books finished", "Date finished"],
    )


def _savings(success: dict[str, Any], unit: str) -> tuple[list[str], list[str], list[str]]:
    amount = _target_amount(success)
    label = f"${amount:,.0f}" if amount is not None else "the target balance"
    unit_name = unit or "currency"
    return (
        [
            f"Set the account or balance that counts toward {label}, and ignore money outside it.",
            "Choose a monthly amount you can add every month until the deadline.",
            "Log the balance on a regular day each month. Do not log a plan "
            "as if the money already moved.",
            "If a month is short, record the smaller transfer rather than skipping the entry.",
        ],
        [
            f"25% of {label}",
            f"50% of {label}",
            f"75% of {label}",
            f"{label} reached",
        ],
        [f"Balance ({unit_name})", "Amount added that month"],
    )


def _fitness(title: str) -> tuple[list[str], list[str], list[str]]:
    return (
        [
            f"Schedule the sessions that move “{title.strip()}”, and keep the same "
            "route or format when you measure.",
            "Log each session with the result that the goal measures, such as time or distance.",
            "Use one session a month as a check against the target, not as a guess "
            "of race-day odds.",
            "If you miss a week, log the miss and continue. A missed week is not "
            "a completed session.",
        ],
        [
            "Training habit in place for two weeks",
            "Halfway through the planned sessions",
            "One measured attempt near the target",
            "Target performance recorded",
        ],
        ["Session result", "Date of the session"],
    )


def _dinners(success: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    amount = _target_amount(success)
    target = f"{int(amount)} dinners" if amount is not None else "the dinner target"
    return (
        [
            "Decide what counts as one dinner, such as a shared meal you hosted.",
            "Put the next few dinners on a calendar so the count is not only a wish.",
            "Log each dinner the day it happens.",
            f"Check the running count against {target} once a month.",
        ],
        ["First dinner logged", "Halfway to the target", target],
        ["Dinners hosted", "Date"],
    )


def _generic(title: str, success: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    metric = str(success.get("metric") or "progress").replace("_", " ")
    amount = _target_amount(success)
    target = f"{amount:g} {metric}" if amount is not None else metric
    name = title.strip() or target
    return (
        [
            f"Write down the action that increases {metric} for “{name}”, "
            "and how often you will do it.",
            f"Log {metric} when it happens. A plan to do it is not a completed measurement.",
            f"Compare the logged total with {target} on a regular cadence before the deadline.",
            "If the action is not measurable yet, narrow it until one log entry "
            "has a number and a date.",
        ],
        [
            f"First {metric} entry logged",
            f"Halfway to {target}",
            f"{target} reached",
        ],
        [metric],
    )


def _is_hiring(blob: str, category: str) -> bool:
    hiring = ("offer", "fde", "forward-deployed", "forward deployed", "interview", "hiring")
    if any(token in blob for token in hiring):
        return True
    return category.lower() in {"career", "hiring"} and "application" in blob


def _is_money(blob: str, unit: str) -> bool:
    if any(token in blob for token in ("raise", "pre-seed", "seed round", "investor")):
        return False
    if unit.lower() in {"$", "usd", "cad", "dollars", "dollar", "currency"}:
        return True
    return any(token in blob for token in ("sav", "net worth", "balance", "deposit"))


def _target_amount(success: dict[str, Any]) -> float | None:
    for key in ("target", "target_value", "threshold", "amount", "value"):
        raw = success.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            return float(str(raw).replace(",", "").replace("$", ""))
        except ValueError:
            continue
    return None


def _looks_like_list(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def _parse_list(text: str) -> list[Any] | None:
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if not isinstance(parsed, list):
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return None
    return parsed if isinstance(parsed, list) else None


def _line(text: str) -> list[str]:
    stripped = text.strip()
    return [stripped[:500]] if stripped else []


def _unique(lines: list[str]) -> list[str]:
    seen: list[str] = []
    for line in lines:
        if line and line not in seen:
            seen.append(line)
    return seen[:_MAX_ITEMS]
