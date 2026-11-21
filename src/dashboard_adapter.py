"""Adapter between the verified pipeline (src/pipeline.py) and the Streamlit dashboard.

The dashboard (app.py, src/dashboard_helpers.py) reads one dictionary:

    leads     one row per input lead: lead_id, company, region, language,
              industry, company_size, activity, vip, score, priority
              ("Critical" ... "Low"), assignment_status, rep_id, rep_name,
              rep_seniority, reason
    reps      one row per rep: rep_id, name, region, language, industry,
              seniority, current_capacity, max_capacity
    metrics   {"elapsed_seconds": total pipeline time}
    warnings  short plain-English notes about cleaning decisions

All routing, scoring and cleaning happens in the verified modules. This file
only renames fields and formats text, so the dashboard always shows exactly
what the pipeline decided.
"""
from __future__ import annotations

from typing import Any

from src.pipeline import run_pipeline as run_core_pipeline


def _warning_notes(summary: list[dict]) -> list[str]:
    notes = []
    for item in summary:
        action = item["action"].replace("_", " ")
        notes.append(f'{item["entity"].capitalize()} {item["field"].replace("_", " ")}: '
                     f'{action} ({item["count"]:,})')
    return notes


def to_dashboard_results(result: dict[str, Any]) -> dict[str, Any]:
    """Convert a src.pipeline result into the dashboard's dictionary."""
    reps = []
    by_id = {}
    for rep in result["updated_reps"]:
        row = {
            "rep_id": rep.get("Rep_ID"),
            "name": rep.get("Name"),
            "region": rep.get("Region"),
            "language": rep.get("Language"),
            "industry": rep.get("Industry_Vertical_Expertise"),
            "seniority": rep.get("Seniority_Level"),
            "current_capacity": rep.get("Current_Capacity", 0),
            "max_capacity": rep.get("Max_Capacity", 0),
        }
        reps.append(row)
        by_id[row["rep_id"]] = row

    leads = []
    for outcome in result["outcomes"]:
        rep = by_id.get(outcome.get("rep_id")) if outcome.get("rep_id") else None
        leads.append({
            "lead_id": outcome.get("record_id") or outcome.get("lead_id"),
            "company": outcome.get("company_name"),
            "region": outcome.get("region"),
            "language": outcome.get("language"),
            "industry": outcome.get("industry"),
            "company_size": outcome.get("company_size"),
            "activity": outcome.get("recent_activity"),
            "vip": bool(outcome.get("is_vip")),
            "score": outcome.get("score", 0),
            "priority": str(outcome.get("priority") or "Low").title(),
            "assignment_status": outcome.get("assignment_status"),
            "rep_id": outcome.get("rep_id") or "",
            "rep_name": rep["name"] if rep else "",
            "rep_seniority": rep["seniority"] if rep else "",
            "reason": outcome.get("reason") or "",
        })

    return {
        "leads": leads,
        "reps": reps,
        "metrics": {"elapsed_seconds": result["timings"].get("total"),
                    "routing_seconds": result["timings"].get("routing_only")},
        "warnings": _warning_notes(result["warning_summary"]),
    }


def run_pipeline(leads_path, reps_path) -> dict[str, Any]:
    """Run the verified pipeline and return the dashboard's dictionary."""
    return to_dashboard_results(run_core_pipeline(leads_path, reps_path))
