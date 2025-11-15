"""Utilities for categorising transactions based on spreadsheet rules."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List


@dataclass(order=True)
class CategoryRule:
    priority: int
    pattern: str
    field: str
    category: str

    def matches(self, transaction: dict) -> bool:
        target = transaction.get(self.field, "") or ""
        return bool(re.search(self.pattern, target, flags=re.IGNORECASE))


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
        hints = ["transfer", "internal", "self", "bnz"]
        return any(hint in description or hint in merchant for hint in hints)
