"""Canonical resolution of a goal's numeric success target.

The Goal Architect writes the target under ``success_definition["target"]``. Older
seeded contracts used ``amount`` or ``value``. Numerical model families must not each
re-invent this lookup: a model that reads the wrong key silently reports the goal as
unpriceable no matter how much evidence the user supplies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from personal_markets.goals.domain import GoalContract

TARGET_KEYS: tuple[str, ...] = ("target", "amount", "value")

_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)$")
_NUMBER = re.compile(r"-?\d[\d,_]*(?:\.\d+)?")
_CURRENCY_SYMBOLS = "$€£¥₹"


@dataclass(frozen=True, slots=True)
class GoalTarget:
    """A resolved numeric target plus where it came from."""

    value: float
    source_key: str
    raw: str
    is_relative: bool = False


def _strip(raw: str) -> str:
    text = raw.strip()
    for symbol in _CURRENCY_SYMBOLS:
        text = text.replace(symbol, "")
    return text.strip()


def parse_number(raw: object) -> float | None:
    """Parse a scalar target such as ``20000``, ``"$20,000"`` or ``"20,000 USD"``."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw)
    if not isinstance(raw, str):
        return None
    text = _strip(raw)
    if not text:
        return None
    match = _NUMBER.search(text)
    if match is None:
        return None
    try:
        return float(match.group(0).replace(",", "").replace("_", ""))
    except ValueError:
        return None


def parse_duration_seconds(raw: object) -> float | None:
    """Parse a clock-style target such as ``"1:40:00"``, ``"20:00"`` or ``1200``."""
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return float(raw)
    if not isinstance(raw, str):
        return None
    text = _strip(raw)
    match = _CLOCK.search(text)
    if match is None:
        return parse_number(text)
    hours, minutes, seconds = match.groups()
    total = float(minutes) * 60.0 + float(seconds)
    if hours is not None:
        total += float(hours) * 3600.0
    return total


def _is_relative(raw: str) -> bool:
    """A target expressed against another quantity cannot be resolved on its own."""
    lowered = raw.lower()
    return "%" in lowered or "percent" in lowered


def resolve_target(
    goal: GoalContract, *, as_duration: bool = False
) -> GoalTarget | None:
    """Resolve the goal's numeric target from the canonical key, then legacy keys."""
    definition = goal.success_definition
    for key in TARGET_KEYS:
        if key not in definition:
            continue
        raw = definition[key]
        if raw is None:
            continue
        text = str(raw)
        parsed = parse_duration_seconds(raw) if as_duration else parse_number(raw)
        if parsed is None:
            continue
        return GoalTarget(
            value=parsed,
            source_key=key,
            raw=text,
            is_relative=_is_relative(text),
        )
    return None


def resolve_target_number(goal: GoalContract) -> float | None:
    """Absolute numeric target, or ``None`` when the goal states a relative one."""
    target = resolve_target(goal)
    if target is None or target.is_relative:
        return None
    return target.value


def resolve_target_duration_seconds(goal: GoalContract) -> float | None:
    target = resolve_target(goal, as_duration=True)
    if target is None or target.is_relative:
        return None
    return target.value


_CURRENCY_WORDS = re.compile(
    r"\b(usd|cad|eur|gbp|aud|inr|jpy|chf|dollars?|euros?|pounds?|rupees?|yen)\b"
)


def target_is_monetary(goal: GoalContract) -> bool:
    """Whether the goal's success target is denominated in money.

    Routing finance goals on nouns ("savings", "net worth") misses every synonym a user
    might pick — an emergency fund, a down payment, a rainy-day pot. What actually
    decides whether the wealth-accumulation model applies is the *dimension* of the
    target, so that is what this asks: does the goal state an amount of money?
    """
    definition = goal.success_definition
    declared = str(definition.get("unit") or definition.get("currency") or "")
    parts = [declared, str(definition.get("metric") or ""), goal.title]
    parts.extend(str(definition[key]) for key in TARGET_KEYS if key in definition)
    blob = " ".join(parts)
    if any(symbol in blob for symbol in _CURRENCY_SYMBOLS):
        return True
    return _CURRENCY_WORDS.search(blob.lower()) is not None


def target_direction(goal: GoalContract, *, default: str = "at_least") -> str:
    operator = str(goal.success_definition.get("operator") or "").strip()
    if operator in {"<=", "<"}:
        return "at_most"
    if operator in {">=", ">"}:
        return "at_least"
    return default
