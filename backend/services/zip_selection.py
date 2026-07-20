from __future__ import annotations

from datetime import datetime, date
from typing import Iterable


def lei_from_zip(name: str) -> str:
    return name.split(".")[0]


def date_from_zip(name: str) -> str:
    """Extract YYYY-MM-DD from a zip filename, if present."""
    for part in name.split("_"):
        if len(part) == 10 and part[4] == "-" and part[7] == "-":
            return part
    return ""


def _parse_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _template_priority(name: str) -> int:
    upper = name.upper()
    if "NONREMDISDOCS" in upper:
        return 0
    if "REMDISDOCS" in upper:
        return 1
    return 2


def _best_candidate(names: list[str]) -> str | None:
    if not names:
        return None
    # Prefer NONREMDISDOCS, then the lexicographically newest filename.
    return max(names, key=lambda n: (-_template_priority(n), n))


def select_zip_for_lei(zip_names: Iterable[str], lei: str, report_date: str = "") -> str | None:
    """
    Select the most appropriate zip for a LEI.

    Priority order:
    1. Exact report_date match.
    2. If no exact match exists, the closest earlier date.
    3. If there is no earlier date, the closest later date.
    4. Within the same date, prefer NONREMDISDOCS over REMDISDOCS.
    5. If no date can be parsed, fall back to the best template/filename.
    """
    candidates = [name for name in zip_names if lei_from_zip(name) == lei]
    if not candidates:
        return None

    requested = _parse_date(report_date)
    parsed: list[tuple[str, date | None]] = [(name, _parse_date(date_from_zip(name))) for name in candidates]

    if requested is not None:
        exact = [name for name, parsed_date in parsed if parsed_date == requested]
        chosen = _best_candidate(exact)
        if chosen:
            return chosen

        earlier_dates = sorted({parsed_date for _, parsed_date in parsed if parsed_date and parsed_date < requested})
        if earlier_dates:
            target = earlier_dates[-1]
            chosen = _best_candidate([name for name, parsed_date in parsed if parsed_date == target])
            if chosen:
                return chosen

        later_dates = sorted({parsed_date for _, parsed_date in parsed if parsed_date and parsed_date > requested})
        if later_dates:
            target = later_dates[0]
            chosen = _best_candidate([name for name, parsed_date in parsed if parsed_date == target])
            if chosen:
                return chosen

    dated_candidates = [name for name, parsed_date in parsed if parsed_date is not None]
    if dated_candidates:
        latest_date = max(parsed_date for _, parsed_date in parsed if parsed_date is not None)
        chosen = _best_candidate([name for name, parsed_date in parsed if parsed_date == latest_date])
        if chosen:
            return chosen

    return _best_candidate(candidates)
