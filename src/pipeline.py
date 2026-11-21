"""End-to-end pipeline: CSV files in, routed results and dashboard metrics out.

Stages, in order:

    load_data -> normalize_data -> score_leads -> route_leads

``run_pipeline`` is the single entry point for the dashboard and for tests. It
works fully in memory, never modifies the CSV files, and never changes the
cleaned representative list it starts from, so every run begins at baseline
capacity and a Reset is just "discard the result and keep the baseline".

Result dictionary (all keys always present):

    dataset               label such as "sample" or "scale" (or None)
    outcomes              every lead exactly once, in original input order
    assignments           leads routed to a rep (assignment_status "Assigned")
    overflow              Manager Review leads, each with a ``reason``
    scored_leads          scored leads before routing
    baseline_reps         cleaned reps at starting capacity (never modified)
    updated_reps          reps with capacity after routing
    rep_warnings          reps excluded from routing, with reasons
    normalization_warnings  every cleaning decision that was logged
    warning_summary       warnings grouped as (entity, field, action, count)
    metrics               KPI numbers (see ``build_metrics``)
    timings               seconds per stage; ``routing_only`` and ``total``
"""
from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from src.data_loader import load_data
from src.normalize import normalize_data, summarize_warnings
from src.routing import route_leads
from src.scoring import score_leads

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

DATASETS = {
    "sample": ("leads_sample.csv", "reps_sample.csv"),
    "scale": ("leads_scale.csv", "reps_scale.csv"),
}

PRIORITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def dataset_paths(name: str, data_dir: Optional[Path] = None) -> tuple[Path, Path]:
    """Return (leads_path, reps_path) for "sample" or "scale"."""
    if name not in DATASETS:
        raise ValueError(f"Unknown dataset {name!r}; choose from {sorted(DATASETS)}")
    folder = Path(data_dir) if data_dir else DATA_DIR
    leads_file, reps_file = DATASETS[name]
    return folder / leads_file, folder / reps_file


def rep_utilization(reps: list[dict]) -> list[dict]:
    """One compact row per rep: load, capacity, and percent used."""
    rows = []
    for rep in reps:
        current = rep.get("Current_Capacity")
        maximum = rep.get("Max_Capacity")
        usable = isinstance(current, int) and isinstance(maximum, int) and maximum > 0
        rows.append({
            "rep_id": rep.get("Rep_ID"),
            "name": rep.get("Name"),
            "seniority": rep.get("Seniority_Level"),
            "region": rep.get("Region"),
            "language": rep.get("Language"),
            "industry": rep.get("Industry_Vertical_Expertise"),
            "current_capacity": current,
            "max_capacity": maximum,
            "utilization": (current / maximum) if usable else 0.0,
            "at_capacity": bool(usable and current >= maximum),
        })
    return rows


def build_metrics(scored: list[dict], routed: dict[str, Any], warnings: list[dict],
                  updated_reps: list[dict]) -> dict[str, Any]:
    """KPI numbers for the dashboard. All values come from actual results."""
    route_metrics = routed["metrics"]
    total = route_metrics["total_leads"]
    assigned = route_metrics["assigned_count"]
    review = route_metrics["manager_review_count"]

    priority_counts = Counter(row.get("priority") for row in scored)
    assigned_by_priority = Counter(row.get("priority") for row in routed["assignments"])
    review_by_priority = Counter(row.get("priority") for row in routed["overflow"])

    capacity_total = sum(
        rep["Max_Capacity"] for rep in updated_reps
        if isinstance(rep.get("Max_Capacity"), int) and rep["Max_Capacity"] > 0
    )
    capacity_used = sum(
        rep["Current_Capacity"] for rep in updated_reps
        if isinstance(rep.get("Current_Capacity"), int)
    )
    utilization = rep_utilization(updated_reps)

    return {
        "total_leads": total,
        "assigned_count": assigned,
        "manager_review_count": review,
        "assignment_rate": route_metrics["assignment_rate"],
        "manager_review_rate": (review / total) if total else 0.0,
        "review_counts_by_reason": dict(route_metrics["review_counts_by_reason"]),
        "priority_counts": {p: priority_counts.get(p, 0) for p in PRIORITIES},
        "assigned_by_priority": {p: assigned_by_priority.get(p, 0) for p in PRIORITIES},
        "review_by_priority": {p: review_by_priority.get(p, 0) for p in PRIORITIES},
        "vip_count": sum(1 for row in scored if row.get("is_vip")),
        "reps_total": len(updated_reps),
        "reps_excluded": route_metrics["excluded_rep_count"],
        "reps_at_capacity": sum(1 for row in utilization if row["at_capacity"]),
        "capacity_total": capacity_total,
        "capacity_used": capacity_used,
        "capacity_utilization": (capacity_used / capacity_total) if capacity_total else 0.0,
        "normalization_warning_count": len(warnings),
    }


def run_pipeline(leads_path, reps_path, dataset: Optional[str] = None) -> dict[str, Any]:
    """Load, clean, score and route one pair of CSV files.

    Raises FileNotFoundError if a path does not exist and SchemaError (a
    ValueError) if a required column is missing. Everything else, including
    messy or missing values, is handled by the cleaning policies and shows up
    in ``normalization_warnings`` or the Manager Review queue.
    """
    started = time.perf_counter()
    raw_leads, raw_reps = load_data(leads_path, reps_path)
    loaded = time.perf_counter()

    leads, baseline_reps, warnings = normalize_data(raw_leads, raw_reps)
    normalized = time.perf_counter()

    scored = score_leads(leads)
    scored_at = time.perf_counter()

    routed = route_leads(scored, baseline_reps)
    finished = time.perf_counter()

    outcomes = sorted(routed["assignments"] + routed["overflow"],
                      key=lambda row: row["source_index"])
    summary = [
        {"entity": e, "field": f, "action": a, "count": c}
        for (e, f, a), c in sorted(summarize_warnings(warnings).items())
    ]
    return {
        "dataset": dataset,
        "outcomes": outcomes,
        "assignments": routed["assignments"],
        "overflow": routed["overflow"],
        "scored_leads": scored,
        "baseline_reps": baseline_reps,
        "updated_reps": routed["updated_reps"],
        "rep_warnings": routed["rep_warnings"],
        "normalization_warnings": warnings,
        "warning_summary": summary,
        "metrics": build_metrics(scored, routed, warnings, routed["updated_reps"]),
        "timings": {
            "load": loaded - started,
            "normalize": normalized - loaded,
            "score": scored_at - normalized,
            "routing_only": finished - scored_at,
            "total": finished - started,
        },
    }


def run_dataset(name: str, data_dir: Optional[Path] = None) -> dict[str, Any]:
    """Run "sample" or "scale" from the data folder."""
    leads_path, reps_path = dataset_paths(name, data_dir)
    return run_pipeline(leads_path, reps_path, dataset=name)


def empty_state(baseline_reps: Optional[list[dict]] = None) -> dict[str, Any]:
    """A cleared result: no outputs, reps shown at baseline capacity."""
    reps = [dict(rep) for rep in (baseline_reps or [])]
    empty_counts = {p: 0 for p in PRIORITIES}
    return {
        "dataset": None,
        "outcomes": [], "assignments": [], "overflow": [], "scored_leads": [],
        "baseline_reps": reps, "updated_reps": [dict(rep) for rep in reps],
        "rep_warnings": [], "normalization_warnings": [], "warning_summary": [],
        "metrics": {
            "total_leads": 0, "assigned_count": 0, "manager_review_count": 0,
            "assignment_rate": 0.0, "manager_review_rate": 0.0,
            "review_counts_by_reason": {}, "priority_counts": dict(empty_counts),
            "assigned_by_priority": dict(empty_counts),
            "review_by_priority": dict(empty_counts), "vip_count": 0,
            "reps_total": len(reps), "reps_excluded": 0, "reps_at_capacity": 0,
            "capacity_total": sum(r["Max_Capacity"] for r in reps
                              if isinstance(r.get("Max_Capacity"), int) and r["Max_Capacity"] > 0),
            "capacity_used": 0, "capacity_utilization": 0.0,
            "normalization_warning_count": 0,
        },
        "timings": {},
    }


def reset_state(result: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Clear outputs and put every rep back to its baseline capacity.

    Pass the last result to keep the rep list visible at baseline, or nothing
    for a fully empty state. The CSV files and the baseline are never touched.
    """
    baseline = result["baseline_reps"] if result else None
    return empty_state(baseline)
