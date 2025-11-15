"""Utilities for categorising transactions based on spreadsheet rules."""
from __future__ import annotations

import operator
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class AmountCondition:
    """Represents a numeric constraint (comparison or exact matches)."""

    operator_symbol: Optional[str] = None
    threshold: Optional[float] = None
    accepted_values: tuple[float, ...] = ()

    def matches(self, amount: Optional[float]) -> bool:
        if amount is None:
            return False
        if self.accepted_values:
            return any(amount == value for value in self.accepted_values)
        if self.operator_symbol and self.threshold is not None:
            comparator = _COMPARATORS.get(self.operator_symbol)
            if not comparator:
                return False
            return comparator(amount, self.threshold)
        return False


@dataclass(order=True)
class CategoryRule:
    priority: int
    pattern: str
    field: str
    category: str
    amount_condition: AmountCondition | None = field(default=None, compare=False)

    def matches(self, transaction: dict) -> bool:
        target = transaction.get(self.field, "") or ""
        if not re.search(self.pattern, target, flags=re.IGNORECASE):
            return False
        if self.amount_condition:
            amount_value = _coerce_amount(transaction.get("amount"))
            if not self.amount_condition.matches(amount_value):
                return False
        return True


class Categoriser:
    def __init__(self, rules: Iterable[dict]):
        self._rules: List[CategoryRule] = []
        for rule in rules:
            try:
                priority = int(rule.get("priority", 1000))
            except (ValueError, TypeError):
                priority = 1000
            pattern = rule.get("pattern", "").strip()
            if not pattern:
                continue
            self._rules.append(
                CategoryRule(
                    priority=priority,
                    pattern=pattern,
                    field=rule.get("field", "merchant_normalised"),
                    category=rule.get("category", "Uncategorised"),
                    amount_condition=_parse_amount_condition(rule.get("amount_condition", "")),
                )
            )
        self._rules.sort()

    def categorise(self, transaction: dict) -> str:
        for rule in self._rules:
            if rule.matches(transaction):
                return rule.category
        return "Uncategorised"

    @staticmethod
    def detect_transfer(transaction: dict) -> bool:
        description = (transaction.get("description_raw") or "").lower()
        merchant = (transaction.get("merchant_normalised") or "").lower()
        hints = ["internet xfr", "transfer", "internal", "self", "bnz"]
        return any(hint in description or hint in merchant for hint in hints)


_COMPARATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "=": operator.eq,
}


def _coerce_amount(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _parse_amount_condition(raw_value: object) -> AmountCondition | None:
    if not raw_value:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    normalized = text.lower()
    replacements = [
        ("greater than or equal to", ">="),
        ("greater than", ">"),
        ("more than", ">"),
        ("less than or equal to", "<="),
        ("less than", "<"),
        ("fewer than", "<"),
        ("at least", ">="),
        ("at most", "<="),
        ("no more than", "<="),
        ("no less than", ">="),
        ("equal to", "="),
    ]
    for phrase, symbol in replacements:
        normalized = normalized.replace(phrase, symbol)
    normalized = normalized.replace("dollars", "").replace("dollar", "")
    normalized = normalized.replace("nz$", "$")
    normalized = normalized.replace("nzd", "")
    normalized = normalized.replace(",", "")
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # Handle exact numeric matches and simple OR combinations.
    if "or" in normalized:
        parts = [part.strip() for part in re.split(r"\bor\b", normalized) if part.strip()]
        values = [_parse_numeric_literal(part) for part in parts]
        if parts and all(value is not None for value in values):
            return AmountCondition(accepted_values=tuple(value for value in values if value is not None))

    literal_value = _parse_numeric_literal(normalized)
    if literal_value is not None:
        return AmountCondition(accepted_values=(literal_value,))

    condensed = normalized.replace(" ", "")
    match = re.search(r"(>=|<=|>|<|==|=)\$?(-?\d+(?:\.\d+)?)", condensed)
    if not match:
        return None
    operator_symbol = match.group(1)
    if operator_symbol == "==":
        operator_symbol = "="
    if operator_symbol not in _COMPARATORS:
        return None
    try:
        threshold = float(match.group(2))
    except ValueError:
        return None
    return AmountCondition(operator_symbol=operator_symbol, threshold=threshold)


def _parse_numeric_literal(text: str) -> Optional[float]:
    cleaned = text.replace(" ", "")
    match = re.fullmatch(r"\$?(-?\d+(?:\.\d+)?)", cleaned)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None
