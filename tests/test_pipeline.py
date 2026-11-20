"""Integration tests for src/pipeline.py (load, normalize, score, route)."""
import copy
from pathlib import Path

import pytest

from src.pipeline import (
    DATA_DIR, PRIORITIES, dataset_paths, empty_state, rep_utilization,
    reset_state, run_dataset, run_pipeline,
)

LEAD_HEADER = ("Lead_ID,Company_Name,Region,Language,Industry_Vertical,"
               "Company_Size,Recent_Activity,VIP_Referral\n")
REP_HEADER = ("Rep_ID,Name,Region,Language,Industry_Vertical_Expertise,"
              "Seniority_Level,Current_Capacity,Max_Capacity\n")

needs_sample = pytest.mark.skipif(
    not all(p.exists() for p in dataset_paths("sample")), reason="sample data missing")
needs_scale = pytest.mark.skipif(
    not all(p.exists() for p in dataset_paths("scale")), reason="scale data missing")


def write_csvs(tmp_path, leads, reps):
    leads_path, reps_path = tmp_path / "leads.csv", tmp_path / "reps.csv"
    leads_path.write_text(LEAD_HEADER + "".join(leads), encoding="utf-8")
    reps_path.write_text(REP_HEADER + "".join(reps), encoding="utf-8")
    return leads_path, reps_path


def vip(lead_id):
    return f"{lead_id},Acme,North America,English,Technology,50,,True\n"


def plain(lead_id, size="5"):
    return f"{lead_id},Acme,North America,English,Technology,{size},,False\n"


def rep(rep_id, level, maximum):
    return f"{rep_id},Name {rep_id},North America,English,Technology,{level},0,{maximum}\n"


def assert_complete(result, expected_leads):
    """Every input lead appears exactly once and the counts add up."""
    outcomes = result["outcomes"]
    assert len(outcomes) == expected_leads
    assert sorted(row["source_index"] for row in outcomes) == list(range(expected_leads))
    assert len({row["record_id"] for row in outcomes}) == expected_leads
    metrics = result["metrics"]
    assert metrics["assigned_count"] + metrics["manager_review_count"] == expected_leads
    assert metrics["total_leads"] == expected_leads
    assert sum(metrics["priority_counts"].values()) == expected_leads
    for row in result["overflow"]:
        assert row["assignment_status"] == "Manager Review" and row["reason"]
    for row in result["assignments"]:
        assert row["assignment_status"] == "Assigned" and row["rep_id"]


def assert_capacity_respected(result):
    load = {}
    for row in result["assignments"]:
        load[row["rep_id"]] = load.get(row["rep_id"], 0) + 1
    for rep_row in result["updated_reps"]:
        assert rep_row["Current_Capacity"] == load.get(rep_row["Rep_ID"], 0)
        assert rep_row["Current_Capacity"] <= rep_row["Max_Capacity"]


# ---------- small synthetic datasets (always run) ----------

def test_critical_goes_to_senior_then_manager_never_junior(tmp_path):
    paths = write_csvs(
        tmp_path,
        [vip("L1"), vip("L2"), vip("L3"), plain("L4")],
        [rep("R1", "Senior", 1), rep("R2", "Manager", 1), rep("R3", "Junior", 5)],
    )
    result = run_pipeline(*paths)
    assert_complete(result, 4)
    by_lead = {row["lead_id"]: row for row in result["outcomes"]}
    assert by_lead["L1"]["rep_id"] == "R1"           # Senior first
    assert by_lead["L2"]["rep_id"] == "R2"           # then Manager
    assert by_lead["L3"]["assignment_status"] == "Manager Review"
    assert by_lead["L3"]["reason"] == "Eligible representatives at capacity"
    assert by_lead["L4"]["rep_id"] == "R3"           # non-critical can use Junior
    assert_capacity_respected(result)


def test_round_robin_spreads_leads_across_equal_reps(tmp_path):
    paths = write_csvs(
        tmp_path,
        [plain(f"L{i}") for i in range(6)],
        [rep("R1", "Junior", 10), rep("R2", "Junior", 10), rep("R3", "Junior", 10)],
    )
    result = run_pipeline(*paths)
    loads = {r["Rep_ID"]: r["Current_Capacity"] for r in result["updated_reps"]}
    assert loads == {"R1": 2, "R2": 2, "R3": 2}


def test_no_matching_rep_goes_to_manager_review_with_reason(tmp_path):
    leads = [f"L1,Acme,Europe,German,Retail,5,,False\n"]
    paths = write_csvs(tmp_path, leads, [rep("R1", "Senior", 5)])
    result = run_pipeline(*paths)
    assert_complete(result, 1)
    assert result["overflow"][0]["reason"] == "No matching representative"


def test_messy_values_do_not_fail_or_drop_leads(tmp_path):
    leads = [
        "L1,Acme, NORTH  AMERICA ,EN,technology,,Requested Live Demo,Unknown\n",
        "L2,Acme,,,,,,\n",
        "L3,Acme,Nort America,english,Technology,5k,Attended Webinar,false\n",
    ]
    paths = write_csvs(tmp_path, leads, [rep("R1", "Junior", 5)])
    result = run_pipeline(*paths)
    assert_complete(result, 3)
    assert result["metrics"]["normalization_warning_count"] > 0
    assert result["warning_summary"]


def test_empty_leads_file_returns_zeroes(tmp_path):
    paths = write_csvs(tmp_path, [], [rep("R1", "Junior", 5)])
    result = run_pipeline(*paths)
    assert result["metrics"]["total_leads"] == 0
    assert result["metrics"]["assignment_rate"] == 0.0
    assert result["outcomes"] == []


def test_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_pipeline(tmp_path / "nope.csv", tmp_path / "also_nope.csv")


def test_unknown_dataset_name_is_rejected():
    with pytest.raises(ValueError):
        run_dataset("huge")


def test_running_twice_gives_identical_results(tmp_path):
    paths = write_csvs(
        tmp_path, [plain(f"L{i}") for i in range(20)],
        [rep("R1", "Junior", 5), rep("R2", "Senior", 5)])
    first, second = run_pipeline(*paths), run_pipeline(*paths)
    pairs = lambda r: [(o["source_index"], o["rep_id"], o["assignment_status"]) for o in r["outcomes"]]
    assert pairs(first) == pairs(second)
    assert first["metrics"] == second["metrics"]


def test_baseline_reps_are_never_modified_by_a_run(tmp_path):
    paths = write_csvs(tmp_path, [plain("L1"), plain("L2")], [rep("R1", "Junior", 5)])
    result = run_pipeline(*paths)
    assert all(r["Current_Capacity"] == 0 for r in result["baseline_reps"])
    assert result["updated_reps"][0]["Current_Capacity"] == 2


def test_reset_clears_outputs_and_restores_baseline_capacity(tmp_path):
    paths = write_csvs(tmp_path, [plain("L1"), plain("L2")], [rep("R1", "Junior", 5)])
    result = run_pipeline(*paths)
    cleared = reset_state(result)
    assert cleared["outcomes"] == [] and cleared["assignments"] == [] and cleared["overflow"] == []
    assert cleared["metrics"]["total_leads"] == 0
    assert all(r["Current_Capacity"] == 0 for r in cleared["updated_reps"])
    assert cleared["updated_reps"][0]["Rep_ID"] == "R1"
    # reset must not damage the earlier result's baseline
    assert all(r["Current_Capacity"] == 0 for r in result["baseline_reps"])


def test_run_after_reset_matches_original_run(tmp_path):
    paths = write_csvs(tmp_path, [plain(f"L{i}") for i in range(10)], [rep("R1", "Junior", 4)])
    before = run_pipeline(*paths)
    reset_state(before)
    after = run_pipeline(*paths)
    assert before["metrics"] == after["metrics"]


def test_empty_state_with_no_result_is_valid():
    state = reset_state(None)
    assert state["metrics"]["total_leads"] == 0 and state["updated_reps"] == []


def test_rep_utilization_rows(tmp_path):
    paths = write_csvs(tmp_path, [plain("L1")], [rep("R1", "Junior", 4)])
    rows = rep_utilization(run_pipeline(*paths)["updated_reps"])
    assert rows[0]["rep_id"] == "R1" and rows[0]["max_capacity"] == 4
    assert rows[0]["utilization"] == pytest.approx(0.25) and not rows[0]["at_capacity"]


def test_timings_separate_routing_from_total(tmp_path):
    paths = write_csvs(tmp_path, [plain("L1")], [rep("R1", "Junior", 4)])
    timings = run_pipeline(*paths)["timings"]
    assert {"load", "normalize", "score", "routing_only", "total"} <= set(timings)
    assert 0 <= timings["routing_only"] <= timings["total"]


def test_csv_files_are_not_modified(tmp_path):
    paths = write_csvs(tmp_path, [plain("L1")], [rep("R1", "Junior", 4)])
    before = [p.read_bytes() for p in paths]
    run_pipeline(*paths)
    assert [p.read_bytes() for p in paths] == before


# ---------- the provided datasets (skipped if the files are absent) ----------

@needs_sample
def test_sample_dataset_end_to_end():
    result = run_dataset("sample")
    assert result["dataset"] == "sample"
    assert_complete(result, 100)
    assert_capacity_respected(result)


@needs_scale
def test_scale_dataset_end_to_end():
    result = run_dataset("scale")
    assert_complete(result, 50000)
    assert_capacity_respected(result)
    assert len(result["baseline_reps"]) == 1600
    assert all(r["Current_Capacity"] == 0 for r in result["baseline_reps"])
    assert result["timings"]["total"] < 60        # generous ceiling, not a benchmark


@needs_sample
@needs_scale
def test_switching_datasets_does_not_contaminate_results():
    fresh_sample = run_dataset("sample")["metrics"]
    run_dataset("scale")
    assert run_dataset("sample")["metrics"] == fresh_sample


@needs_scale
def test_critical_leads_never_assigned_to_juniors_at_scale():
    result = run_dataset("scale")
    level = {r["Rep_ID"]: r["Seniority_Level"] for r in result["updated_reps"]}
    critical = [row for row in result["assignments"] if row["priority"] == "CRITICAL"]
    assert critical
    assert all(level[row["rep_id"]] in ("Senior", "Manager") for row in critical)
