"""Tests for src/dashboard_adapter.py and the dashboard app (Streamlit AppTest)."""
import pytest

from src.dashboard_adapter import run_pipeline, to_dashboard_results
from src.pipeline import dataset_paths, run_dataset

needs_sample = pytest.mark.skipif(
    not all(p.exists() for p in dataset_paths("sample")), reason="sample data missing")
needs_scale = pytest.mark.skipif(
    not all(p.exists() for p in dataset_paths("scale")), reason="scale data missing")

LEAD_KEYS = {"lead_id", "company", "region", "language", "industry", "company_size", "activity",
             "vip", "score", "priority", "assignment_status", "rep_id", "rep_name",
             "rep_seniority", "reason"}
REP_KEYS = {"rep_id", "name", "region", "language", "industry", "seniority",
            "current_capacity", "max_capacity"}


@needs_sample
def test_adapter_shapes_match_what_the_dashboard_reads():
    leads_path, reps_path = dataset_paths("sample")
    out = run_pipeline(leads_path, reps_path)
    assert set(out) >= {"leads", "reps", "metrics", "warnings"}
    assert len(out["leads"]) == 100 and len(out["reps"]) == 10
    assert all(LEAD_KEYS <= set(row) for row in out["leads"])
    assert all(REP_KEYS <= set(row) for row in out["reps"])
    assert out["metrics"]["elapsed_seconds"] >= 0
    assert all(isinstance(note, str) for note in out["warnings"])


@needs_sample
def test_priority_labels_and_statuses_are_dashboard_style():
    leads_path, reps_path = dataset_paths("sample")
    out = run_pipeline(leads_path, reps_path)
    assert {row["priority"] for row in out["leads"]} <= {"Critical", "High", "Medium", "Low"}
    assert {row["assignment_status"] for row in out["leads"]} <= {"Assigned", "Manager Review"}
    for row in out["leads"]:
        if row["assignment_status"] == "Assigned":
            assert row["rep_id"] and row["rep_name"] and not row["reason"]
        else:
            assert not row["rep_id"] and row["reason"]


@needs_sample
def test_adapter_matches_core_pipeline_counts():
    core = run_dataset("sample")
    out = to_dashboard_results(core)
    assigned = sum(1 for row in out["leads"] if row["assignment_status"] == "Assigned")
    assert assigned == core["metrics"]["assigned_count"]
    assert sum(r["current_capacity"] for r in out["reps"]) == assigned


@needs_scale
def test_adapter_scale_keeps_every_lead_and_unique_ids():
    leads_path, reps_path = dataset_paths("scale")
    out = run_pipeline(leads_path, reps_path)
    assert len(out["leads"]) == 50000 and len(out["reps"]) == 1600
    assert len({row["lead_id"] for row in out["leads"]}) == 50000
    assert all(r["current_capacity"] <= r["max_capacity"] for r in out["reps"])


@needs_sample
@needs_scale
def test_dashboard_buttons_run_both_datasets_and_reset():
    pytest.importorskip("streamlit")
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    app = Path(__file__).resolve().parent.parent / "app.py"
    at = AppTest.from_file(str(app), default_timeout=180)
    at.run()
    assert not at.exception

    def click(label):
        [b for b in at.button if b.label == label][0].click().run()
        assert not at.exception

    def counts():
        leads = at.session_state["results"]["leads"]
        assigned = sum(1 for lead in leads if lead["assignment_status"] == "Assigned")
        return len(leads), assigned

    click("▶ Run Sample")
    assert counts()[0] == 100
    for tab in ("Lead Queue", "Manager Review", "Rep Capacity", "Overview"):
        at.radio(key="tab").set_value(tab).run()
        assert not at.exception
    click("▶ Run Scale")
    total, assigned = counts()
    assert total == 50000 and 0 < assigned <= 50000
    click("↺ Reset")
    assert "results" not in at.session_state
    click("▶ Run Sample")
    assert counts()[0] == 100
