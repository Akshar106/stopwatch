"""Grounding check: every number in a model answer must come from tool results (or the question itself).

An answer that cites a number we never computed is treated as a hallucination and replaced by the
structured facts, so users never see an invented statistic.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


def numbers_in_text(text: str) -> list[float]:
    # Ignore clock times like 8:05 (hours/minutes are checked as separate numbers) and ordinals' suffixes.
    return [float(m) for m in _NUMBER.findall(text.replace(",", ""))]


def numbers_in_json(obj: Any) -> set[float]:
    out: set[float] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int | float):
        out.add(float(obj))
    elif isinstance(obj, str):
        out.update(numbers_in_text(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= numbers_in_json(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= numbers_in_json(v)
    return out


def _supported(n: float, allowed: Iterable[float]) -> bool:
    for a in allowed:
        if abs(n - a) < 1e-9 or abs(n - round(a)) < 1e-9 or abs(n - round(a, 1)) < 1e-9:
            return True
        if abs(n) == abs(a):  # "3 minutes early" for -3
            return True
    return False


def ungrounded_numbers(answer: str, tool_results: list[dict[str, Any]], question: str) -> list[float]:
    allowed = numbers_in_json(tool_results) | set(numbers_in_text(question))
    allowed |= {0.0, 1.0, 2.0}  # "one", "a couple" spelled as digits are harmless
    return [n for n in numbers_in_text(answer) if not _supported(n, allowed)]


def compact(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
