"""Utility for filtering out transactions via user-defined ignore rules."""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from typing import Iterable, List, Mapping, Optional, Pattern, Sequence

from akahu_client import AkahuTransaction


@dataclass
class IgnoreRule:
    """Represents a single ignore rule matched against Akahu transactions."""

    field_name: str
    pattern: str
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    _regex: Pattern[str] = dataclass_field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._regex = re.compile(self.pattern, re.IGNORECASE)

    def matches(self, transaction: AkahuTransaction) -> bool:
        value = getattr(transaction, self.field_name, "")
        if value is None:
            value = ""
        if not self._regex.search(str(value)):
            return False
        amount = transaction.amount
        if self.min_amount is not None and amount < self.min_amount:
            return False
        if self.max_amount is not None and amount > self.max_amount:
            return False
        return True


def build_ignore_rules(raw_rules: Optional[Sequence[Mapping[str, object]]]) -> List[IgnoreRule]:
    """Create :class:`IgnoreRule` instances from config values."""

    rules: List[IgnoreRule] = []
    if not raw_rules:
        return rules
    for raw in raw_rules:
        if not raw:
            continue
        pattern = str(raw.get("pattern", ""))
        if not pattern:
            continue
        field_name = str(raw.get("field") or "description_raw")
        min_amount = _to_float(raw.get("min_amount"))
        max_amount = _to_float(raw.get("max_amount"))
        rules.append(
            IgnoreRule(field_name=field_name, pattern=pattern, min_amount=min_amount, max_amount=max_amount)
        )
    return rules


def should_ignore(transaction: AkahuTransaction, rules: Iterable[IgnoreRule]) -> bool:
    """Return True if a transaction should be dropped based on provided rules."""

    for rule in rules:
        if rule.matches(transaction):
            return True
    return False


def _to_float(value: object) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
