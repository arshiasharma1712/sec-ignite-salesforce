"""Deterministic, in-memory routing of normalized, scored lead dictionaries.

``route_leads(scored_leads, reps)`` returns assignments, updated_reps, overflow,
metrics, and rep_warnings. Input records are never modified. See
docs/routing.md for the field contract, validation policies, and reset semantics.
There are no imports from the pending scoring/normalization modules.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Mapping
from numbers import Integral
from typing import Any, Optional


_REGIONS = {"north america", "europe", "asia-pacific"}
_LANGUAGES = {"english", "german", "spanish"}
_INDUSTRIES = {"technology", "healthcare", "finance", "manufacturing", "retail", "unknown"}
_SENIORITIES = {"junior", "senior", "manager"}
_TIER_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

_INVALID_LEAD = "Invalid lead record"
_INVALID_SCORE = "Invalid scoring metadata"
_INVALID_SKILLS = "Missing or invalid routing fields"
_NO_MATCH = "No matching representative"
_NO_SENIORITY = "No eligible Senior or Manager"
_AT_CAPACITY = "Eligible representatives at capacity"

SkillKey = tuple[str, str, str]


def _canonical(value: Any, allowed: set[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip().casefold()
    return value if value in allowed else None


def _skill_key(record: Mapping, industry_field: str) -> Optional[SkillKey]:
    region = _canonical(record.get("Region"), _REGIONS)
    language = _canonical(record.get("Language"), _LANGUAGES)
    industry = _canonical(record.get(industry_field), _INDUSTRIES)
    if region is None or language is None or industry is None:
        return None
    return region, language, industry


def _record_copy(record: Any) -> dict:
    if isinstance(record, Mapping):
        return dict(record)
    # Preserve malformed rows too; source_index identifies their input position.
    return {"invalid_record": True, "invalid_record_repr": repr(record)[:200]}


def _rep_identity(record: Mapping) -> Optional[str]:
    value = record.get("Rep_ID")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _integer(value: Any) -> bool:
    return isinstance(value, Integral) and not isinstance(value, bool)


def _valid_capacity(record: Mapping) -> bool:
    current, maximum = record.get("Current_Capacity"), record.get("Max_Capacity")
    return (
        _integer(current) and _integer(maximum)
        and 0 <= current <= maximum
    )


def _scoring_problem(record: Mapping) -> Optional[str]:
    if record.get("invalid_record"):
        return _INVALID_LEAD
    score, priority, vip = (record.get(key) for key in ("score", "priority", "is_vip"))
    if not _integer(score) or not 0 <= score <= 100 or not isinstance(vip, bool):
        return _INVALID_SCORE
    expected = "CRITICAL" if score >= 85 else "HIGH" if score >= 60 else "MEDIUM" if score >= 40 else "LOW"
    if priority != expected or (vip and score != 100):
        return _INVALID_SCORE
    return None


def _lead_order(item: tuple[int, dict, Optional[str]]) -> tuple:
    index, record, problem = item
    if problem:
        return (len(_TIER_RANK), 0, 1, "", index)
    # Matches scoring PR #6's sort_for_routing for valid scored records.
    return (
        _TIER_RANK[record["priority"]], -record["score"],
        0 if record["is_vip"] else 1, str(record.get("Lead_ID") or ""), index,
    )


def _has_capacity(record: Mapping) -> bool:
    return record["Current_Capacity"] < record["Max_Capacity"]


def route_leads(scored_leads: list[dict], reps: list[dict]) -> dict[str, Any]:
    """Route every input lead once, returning new outcome/capacity dictionaries.

    Valid leads are processed by tier, descending score, VIP, Lead_ID, then input
    position. Malformed scored rows follow in input order. Critical leads use
    Seniors before Managers; other leads use all eligible seniorities equally.
    Every round-robin queue and capacity copy belongs to this call only.
    """
    updated_reps = [_record_copy(rep) for rep in reps]
    identities = Counter(_rep_identity(rep) for rep in updated_reps)
    groups: dict[SkillKey, list[int]] = defaultdict(list)
    seniorities: dict[int, str] = {}
    rep_warnings = []

    for index, rep in enumerate(updated_reps):
        identity = _rep_identity(rep)
        skills = _skill_key(rep, "Industry_Vertical_Expertise")
        seniority = _canonical(rep.get("Seniority_Level"), _SENIORITIES)
        problem = None
        if rep.get("invalid_record"):
            problem = "Invalid representative record"
        elif identity is None:
            problem = "Missing or invalid Rep_ID"
        elif identities[identity] > 1:
            problem = "Duplicate Rep_ID"
        elif skills is None:
            problem = _INVALID_SKILLS
        elif seniority is None:
            problem = "Missing or invalid seniority"
        elif not _valid_capacity(rep):
            problem = "Invalid representative capacity"

        if problem:
            rep_warnings.append({
                "source_index": index, "rep_id": rep.get("Rep_ID"), "reason": problem,
            })
        else:
            groups[skills].append(index)
            seniorities[index] = seniority

    # Keep full but otherwise valid reps in groups so no match, no seniority,
    # and exhausted capacity have distinct review explanations.
    senior_queues, manager_queues, experienced_groups = {}, {}, set()
    for skills, indices in groups.items():
        indices.sort(key=lambda index: _rep_identity(updated_reps[index]))
        senior_queues[skills] = deque()
        manager_queues[skills] = deque()
        for index in indices:
            seniority = seniorities[index]
            if seniority in {"senior", "manager"}:
                experienced_groups.add(skills)
                if _has_capacity(updated_reps[index]):
                    queue = senior_queues if seniority == "senior" else manager_queues
                    queue[skills].append(index)

    prepared = []
    for index, lead in enumerate(scored_leads):
        record = _record_copy(lead)
        prepared.append((index, record, _scoring_problem(record)))
    prepared.sort(key=_lead_order)

    assignments, overflow = [], []
    general_queues = None
    for index, lead, problem in prepared:
        outcome = {
            **lead, "source_index": index, "rep_id": None,
            "assignment_status": "Manager Review", "reason": None,
        }
        skills = _skill_key(lead, "Industry_Vertical")
        queue = None
        if problem is None:
            if skills is None:
                problem = _INVALID_SKILLS
            elif skills not in groups:
                problem = _NO_MATCH
            elif lead["priority"] == "CRITICAL":
                if skills not in experienced_groups:
                    problem = _NO_SENIORITY
                else:
                    queue = senior_queues[skills] or manager_queues[skills]
            else:
                if general_queues is None:
                    # All Critical leads have finished. Rebuild from remaining
                    # capacity rather than sharing stale queues between phases.
                    general_queues = {
                        key: deque(i for i in indices if _has_capacity(updated_reps[i]))
                        for key, indices in groups.items()
                    }
                queue = general_queues[skills]

        if problem is None and not queue:
            problem = _AT_CAPACITY
        if problem is not None:
            outcome["reason"] = problem
            overflow.append(outcome)
            continue

        rep_index = queue.popleft()
        rep = updated_reps[rep_index]
        rep["Current_Capacity"] += 1
        if "current_capacity" in rep:
            rep["current_capacity"] = rep["Current_Capacity"]
        if _has_capacity(rep):
            queue.append(rep_index)
        outcome.update(rep_id=rep["Rep_ID"], assignment_status="Assigned")
        assignments.append(outcome)

    total = len(prepared)
    return {
        "assignments": assignments,
        "updated_reps": updated_reps,
        "overflow": overflow,
        "metrics": {
            "total_leads": total,
            "assigned_count": len(assignments),
            "manager_review_count": len(overflow),
            "assignment_rate": len(assignments) / total if total else 0.0,
            "review_counts_by_reason": dict(Counter(row["reason"] for row in overflow)),
            "excluded_rep_count": len(rep_warnings),
        },
        "rep_warnings": rep_warnings,
    }
