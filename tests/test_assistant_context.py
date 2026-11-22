from copy import deepcopy
import json

import pytest

from src.assistant_context import AssistantContext, MAX_ROWS, MAX_TEXT
from src.dashboard_adapter import to_dashboard_results
from src.pipeline import dataset_paths, run_dataset


def test_no_run_and_empty_run_are_distinct():
    context = AssistantContext()
    for name, args in [("get_summary", {}), ("query_leads", {}), ("query_reps", {}),
                       ("lookup_record", {"entity": "lead", "identifier": "L-1"})]:
        assert context.call(name, args)["loaded"] is False
    assert "scoring" in context.call("get_program_rules", {})["rules"]
    empty = AssistantContext({"leads": [], "reps": []}).get_summary()
    assert empty["loaded"] and empty["total_leads"] == empty["assignment_rate"] == 0


def test_summary_distinguishes_capacity_data_quality_and_handled(assistant_results):
    summary = AssistantContext(assistant_results, "Demo").get_summary()
    assert (summary["total_leads"], summary["assigned"], summary["manager_review"], summary["handled"]) == (4, 1, 2, 1)
    assert summary["vip_count"] == 1 and summary["assignment_rate"] == .25
    assert summary["excluded_reps"] == 1 and summary["available_slots_eligible_reps"] == 2
    assert summary["review_reasons"]["groups"] == [
        {"value": "All matching representatives at capacity", "count": 1},
        {"value": "Missing or invalid routing fields", "count": 1}]


def test_lead_filters_aggregate_full_matches_before_limit(assistant_results):
    context = AssistantContext(assistant_results)
    found = context.call("query_leads", {"filters": {"assignment_status": "manager review", "region": " europe "},
                                          "group_by": "reason", "limit": 1})
    assert found["total_matches"] == 2 and found["truncated"]
    assert sum(group["count"] for group in found["groups"]) == 2
    assert found["rows"][0]["lead_id"] == "L-2"
    assert context.query_leads({"vip": True, "search": "unknown"})["total_matches"] == 1
    assert context.query_leads({"min_score": 85, "rep_id": "R-1"})["total_matches"] == 1
    assert context.query_leads({"lead_id": "l-1"})["total_matches"] == 0  # IDs are exact


def test_representative_query_counts_only_eligible_capacity(assistant_results):
    context = AssistantContext(assistant_results)
    found = context.call("query_reps", {"filters": {"eligible": True, "min_remaining": 1}, "group_by": "seniority"})
    assert found["total_matches"] == 1 and found["rows"][0]["rep_id"] == "R-1"
    assert found["available_slots_eligible_reps"] == 2
    excluded = context.query_reps({"eligible": False})
    assert excluded["rows"][0]["exclusion_reason"] and excluded["available_slots_eligible_reps"] == 0
    assert context.query_reps({"seniority": "manager"})["rows"][0]["remaining"] == 0


@pytest.mark.parametrize("change", [{"rep_id": ""}, {"current_capacity": True}, {"max_capacity": "3"},
                                   {"current_capacity": 4}, {"language": "Unknown"}, {"seniority": "Unknown"}])
def test_rep_exclusion_matches_router(assistant_results, change):
    assistant_results["reps"][0].update(change)
    rows = AssistantContext(assistant_results).query_reps()["rows"]
    assert not next(row for row in rows if row["row_index"] == 0)["eligible"]
    assert AssistantContext(assistant_results).get_summary()["excluded_reps"] == 2


def test_duplicate_and_missing_ids_never_select_arbitrary_row(assistant_results):
    assistant_results["leads"][1]["lead_id"] = "L-1"
    assistant_results["reps"][1]["rep_id"] = "R-1"
    assistant_results["reps"][2]["rep_id"] = ""
    context = AssistantContext(assistant_results)
    duplicate = context.lookup_record("lead", "L-1")
    assert duplicate["ambiguous"] and duplicate["total_matches"] == 2
    assert "score_from_current_fields" not in duplicate
    exact = context.lookup_record("lead", "L-1", row_index=1)
    assert not exact["ambiguous"] and exact["rows"][0]["vip"]
    assert context.lookup_record("lead", "missing")["total_matches"] == 0
    assert context.lookup_record("lead", "L-1", row_index=3)["total_matches"] == 0
    assert context.lookup_record("rep", "")["rows"][0]["exclusion_reason"]
    assert context.get_summary()["excluded_reps"] == 3


def test_live_edits_score_discrepancy_and_input_preservation(assistant_results):
    original = deepcopy(assistant_results)
    context = AssistantContext(assistant_results)
    scored = context.lookup_record("lead", "L-1")
    assert scored["matches_stored_score"] and scored["score_from_current_fields"]["size_points"] == 50
    assert assistant_results == original
    assistant_results["leads"][0].update(company_size=20, manual="assigned", overrides={"company_size": 20},
                                        defaults_applied=["Language"])
    assistant_results["reps"][0]["current_capacity"] = 2
    fresh = AssistantContext(assistant_results)
    record = fresh.lookup_record("lead", "L-1")
    assert not record["matches_stored_score"]
    assert record["rows"][0]["manual_action"] == "assigned"
    assert record["rows"][0]["edited_fields"] == ["company_size"]
    assert record["rows"][0]["defaults_applied"] == ["Language"]
    assert fresh.get_summary()["available_slots_eligible_reps"] == 1


@pytest.mark.parametrize("name,args", [
    ("run_pipeline", {}), ("__init__", {}), ("query_leads", {"limit": 21}),
    ("query_leads", {"limit": True}), ("query_leads", {"limit": 0}),
    ("query_leads", {"filters": {"vip": "true"}}), ("query_leads", {"filters": {"min_score": 101}}),
    ("query_leads", {"group_by": "password"}), ("query_leads", {"filters": {"code": "print('hello')"}}),
    ("query_leads", {"filters": {"search": "x" * 201}}), ("get_summary", {"unexpected": 1}),
    ("lookup_record", {"entity": "lead"}), ("lookup_record", {"entity": "file", "identifier": "secret"}),
    ("query_reps", None),
])
def test_only_bounded_read_only_queries_allowed(assistant_results, name, args):
    baseline = deepcopy(assistant_results)
    assert "error" in AssistantContext(assistant_results).call(name, args)
    assert assistant_results == baseline


def test_long_values_are_matched_before_projection_and_groups_are_bounded(assistant_results):
    assistant_results["reps"][0]["rep_id"] = "R" * 180
    assistant_results["reps"][0]["name"] = "x" * 5000 + "needle"
    assistant_results["leads"] = [dict(assistant_results["leads"][0], lead_id=str(i),
                                      company="x" * 5000, reason=str(i)) for i in range(30)]
    context = AssistantContext(assistant_results)
    assert context.query_reps({"rep_id": "R" * 180, "search": "needle"})["total_matches"] == 1
    leads = context.query_leads(group_by="reason")
    assert leads["total_matches"] == leads["total_groups"] == 30
    assert leads["groups_truncated"] and leads["truncated"]
    assert len(leads["groups"]) == len(leads["rows"]) == MAX_ROWS
    assert len(leads["rows"][0]["company"]) < MAX_TEXT + 20


@pytest.mark.skipif(not all(path.exists() for path in dataset_paths("scale")), reason="scale data missing")
def test_supplied_scale_counts_remain_exact_while_rows_stay_bounded():
    core = run_dataset("scale")
    context = AssistantContext(to_dashboard_results(core), "Scale")
    summary = context.get_summary()
    assert summary["total_leads"] == 50000 and summary["total_reps"] == 1600
    assert summary["assigned"] == core["metrics"]["assigned_count"]
    assert summary["excluded_reps"] == core["metrics"]["reps_excluded"]
    rows = context.query_leads({"assignment_status": "Manager Review"}, group_by="reason")
    assert rows["total_matches"] == core["metrics"]["manager_review_count"]
    assert sum(group["count"] for group in rows["groups"]) == rows["total_matches"]
    assert len(rows["rows"]) == MAX_ROWS and len(json.dumps(rows).encode()) < 25000
